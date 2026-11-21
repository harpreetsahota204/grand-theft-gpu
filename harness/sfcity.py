"""Builds San Silicon's ground truth: a real slice of San Francisco as game assets.

Inputs (both fetched at build time, cached under the output folder):
- OpenStreetMap buildings and streets via the Overpass API
  (© OpenStreetMap contributors, ODbL 1.0)
- Elevation from AWS Terrain Tiles ("terrarium" PNG encoding), derived mostly
  from USGS 3DEP in the US (public domain; attribution to Mapzen/AWS Terrain Tiles)

Outputs, in `<out>/sf-city/`:
- `sf-city.glb`: terrain (with the hills), every building extruded to its
  real height and sat on the terrain, drivable streets draped over the ground,
  and a water plane for the bay. One mesh per layer, vertex-coloured.
- `buildings.json`: one row per building (centroid, footprint, height, base
  elevation, OSM type) so a game can pick one to be a data center or a VC office.
- `streets.json`: a routable graph of drivable streets (intersections,
  segments with name, class, lanes, one-way, length, polyline) for traffic AI.
- `meta.json`: bounding box, projection, and attribution.

Real building *names* are deliberately dropped (OSM names towers after companies;
the game uses parody names). Street names are kept: they're public geography.

Coordinates: local metres, origin at the bbox centre, glTF axes:
x = east, y = up (metres above sea level), z = south (so north is -z).

Called by `buildoff assets city` (see `harness.cli`).
"""

import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image
from shapely.geometry import Polygon

# SoMa → Financial District → Embarcadero (south, west, north, east), WGS84.
BBOX: tuple[float, float, float, float] = (37.776, -122.408, 37.797, -122.390)

OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"
TERRAIN_URL: str = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
# Zoom 15 terrarium tiles are ~4 m/pixel at this latitude: enough for SF's hills.
TERRAIN_ZOOM: int = 15
USER_AGENT: str = "grand-theft-gpu-asset-builder/0.1"

TERRAIN_STEP_M: float = 10.0
WATER_LEVEL_M: float = 0.0
METRES_PER_LEVEL: float = 3.2
DEFAULT_HEIGHT_M: float = 10.0
# Buildings sink this far below their lowest corner so they never float on slopes.
FOUNDATION_M: float = 2.0
ROAD_LIFT_M: float = 0.15

# Carriageway width per OSM highway class, in metres. Classes not listed aren't drawn.
ROAD_WIDTH_M: dict[str, float] = {
    "motorway": 14.0, "motorway_link": 7.0, "trunk": 14.0, "trunk_link": 7.0,
    "primary": 14.0, "primary_link": 7.0, "secondary": 12.0, "secondary_link": 6.0,
    "tertiary": 10.0, "tertiary_link": 6.0, "residential": 8.0, "living_street": 6.0,
    "unclassified": 8.0, "service": 5.0, "busway": 7.0,
}  # fmt: skip

# RGBA vertex colours per layer / building type (PS2-era flat palette).
COLOURS: dict[str, list[int]] = {
    "terrain": [118, 128, 102, 255],
    "road": [52, 54, 58, 255],
    "water": [44, 86, 120, 255],
    "office": [176, 182, 190, 255],
    "commercial": [190, 170, 150, 255],
    "residential": [196, 160, 128, 255],
    "other": [168, 168, 160, 255],
}
BUILDING_TYPES: dict[str, str] = {
    "office": "office", "commercial": "commercial", "retail": "commercial",
    "hotel": "commercial", "apartments": "residential", "residential": "residential",
    "house": "residential",
}  # fmt: skip


# ---------- fetching ----------------------------------------------------------


def fetch_osm(cache: Path) -> dict[str, Any]:
    """Downloads buildings and streets in BBOX from Overpass, cached as JSON."""
    if cache.exists():
        return json.loads(cache.read_text())
    s, w, n, e = BBOX
    query = (
        f'[out:json][timeout:120];(way["building"]({s},{w},{n},{e});'
        f'way["highway"]({s},{w},{n},{e}););out body;>;out skel qt;'
    )
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read())
    cache.write_text(json.dumps(data))
    return data


def tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Converts lat/lon to fractional web-mercator tile coordinates at zoom z."""
    n = 2**z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


class Elevation:
    """Samples ground elevation (metres) anywhere in BBOX from terrarium tiles.

    Created once per build; downloads and stitches the covering tiles, caching
    the PNGs under `cache_dir`. `at(lat, lon)` bilinearly interpolates.
    """

    def __init__(self, cache_dir: Path) -> None:
        """Fetches and stitches every zoom-TERRAIN_ZOOM tile covering BBOX."""
        s, w, n, e = BBOX
        x0, y0 = (int(v) for v in tile_xy(n, w, TERRAIN_ZOOM))
        x1, y1 = (int(v) for v in tile_xy(s, e, TERRAIN_ZOOM))
        self.x0, self.y0 = x0, y0
        cache_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for ty in range(y0, y1 + 1):
            row = []
            for tx in range(x0, x1 + 1):
                png = cache_dir / f"{TERRAIN_ZOOM}-{tx}-{ty}.png"
                if not png.exists():
                    url = TERRAIN_URL.format(z=TERRAIN_ZOOM, x=tx, y=ty)
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        png.write_bytes(resp.read())
                rgb = np.asarray(Image.open(io.BytesIO(png.read_bytes())).convert("RGB"), float)
                # Terrarium encoding: height = R*256 + G + B/256 - 32768 (metres).
                row.append(rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768)
            rows.append(np.hstack(row))
        self.grid = np.vstack(rows)

    def at(self, lat: float, lon: float) -> float:
        """Returns interpolated elevation in metres at a point inside BBOX."""
        fx, fy = tile_xy(lat, lon, TERRAIN_ZOOM)
        px = (fx - self.x0) * 256 - 0.5
        py = (fy - self.y0) * 256 - 0.5
        i, j = int(math.floor(py)), int(math.floor(px))
        di, dj = py - i, px - j
        g = self.grid
        i = min(max(i, 0), g.shape[0] - 2)
        j = min(max(j, 0), g.shape[1] - 2)
        top = g[i, j] * (1 - dj) + g[i, j + 1] * dj
        bot = g[i + 1, j] * (1 - dj) + g[i + 1, j + 1] * dj
        return float(top * (1 - di) + bot * di)


# ---------- projection ---------------------------------------------------------


class Projection:
    """Local equirectangular projection around the BBOX centre, in metres.

    Over ~2 km the distortion is far below a building's width. Maps to glTF
    axes: x = east, z = south.
    """

    def __init__(self) -> None:
        """Sets the origin at the BBOX centre."""
        s, w, n, e = BBOX
        self.lat0, self.lon0 = (s + n) / 2, (w + e) / 2
        self.kx = 111_320.0 * math.cos(math.radians(self.lat0))
        self.kz = 110_540.0

    def xz(self, lat: float, lon: float) -> tuple[float, float]:
        """Returns (x east, z south) in metres for a lat/lon."""
        return (lon - self.lon0) * self.kx, -(lat - self.lat0) * self.kz

    def latlon(self, x: float, z: float) -> tuple[float, float]:
        """Inverse of xz: (lat, lon) for local metres."""
        return self.lat0 - z / self.kz, self.lon0 + x / self.kx


# ---------- geometry -------------------------------------------------------------


def inside(lat: float, lon: float) -> bool:
    """True if a point lies within BBOX (OSM returns whole ways that cross its edge)."""
    s, w, n, e = BBOX
    return s <= lat <= n and w <= lon <= e


def coloured(mesh: trimesh.Trimesh, rgba: list[int]) -> trimesh.Trimesh:
    """Paints every vertex of a mesh one flat colour and returns it."""
    mesh.visual.vertex_colors = np.tile(rgba, (len(mesh.vertices), 1))
    return mesh


def finalize(mesh: trimesh.Trimesh, flat: bool) -> trimesh.Trimesh:
    """Drops zero-area faces and sets finite normals, ready for glTF export.

    OSM has duplicate or collinear points that make zero-area triangles; their
    normals are NaN, which stops three.js from loading the file.

    Args:
        mesh: a vertex-coloured mesh
        flat: True for per-face (faceted) normals, False for smooth ones
    """
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    if flat:
        # Unshared vertices give each face its own normal: crisp walls and kerbs.
        mesh.unmerge_vertices()
        normals = np.repeat(mesh.face_normals, 3, axis=0)
    else:
        normals = mesh.vertex_normals
    mesh.vertex_normals = np.nan_to_num(normals)
    return mesh


def terrain_mesh(proj: Projection, elev: Elevation) -> trimesh.Trimesh:
    """Builds a grid mesh of the ground over BBOX at TERRAIN_STEP_M spacing."""
    s, w, n, e = BBOX
    (xmin, zmax), (xmax, zmin) = proj.xz(s, w), proj.xz(n, e)
    xs = np.arange(xmin, xmax + TERRAIN_STEP_M, TERRAIN_STEP_M)
    zs = np.arange(zmin, zmax + TERRAIN_STEP_M, TERRAIN_STEP_M)
    verts = [(x, elev.at(*proj.latlon(x, z)), z) for z in zs for x in xs]
    nx = len(xs)
    faces = []
    for r in range(len(zs) - 1):
        for c in range(nx - 1):
            a, b, d = r * nx + c, r * nx + c + 1, (r + 1) * nx + c
            faces += [(a, d, b), (b, d, d + 1)]
    mesh = trimesh.Trimesh(np.array(verts), np.array(faces), process=False)
    return coloured(mesh, COLOURS["terrain"])


def water_plane(proj: Projection) -> trimesh.Trimesh:
    """A flat plane at sea level; terrain below it (the bay) reads as water."""
    s, w, n, e = BBOX
    (xmin, zmax), (xmax, zmin) = proj.xz(s, w), proj.xz(n, e)
    v = np.array([[xmin, WATER_LEVEL_M, zmin], [xmax, WATER_LEVEL_M, zmin],
                  [xmax, WATER_LEVEL_M, zmax], [xmin, WATER_LEVEL_M, zmax]])  # fmt: skip
    return coloured(trimesh.Trimesh(v, [[0, 2, 1], [0, 3, 2]], process=False), COLOURS["water"])


def parse_height(tags: dict[str, str]) -> float:
    """Returns a building's height in metres from OSM tags, with sensible fallbacks."""
    for key in ("height", "building:height"):
        raw = tags.get(key, "").split()[0] if tags.get(key) else ""
        try:
            return max(float(raw), 3.0)
        except ValueError:
            pass
    try:
        return max(float(tags["building:levels"]) * METRES_PER_LEVEL, 3.0)
    except (KeyError, ValueError):
        return DEFAULT_HEIGHT_M


def build_buildings(
    osm: dict[str, Any], proj: Projection, elev: Elevation
) -> tuple[trimesh.Trimesh, list[dict[str, Any]]]:
    """Extrudes every closed building way onto the terrain.

    Returns:
        (one merged, vertex-coloured mesh of all buildings, per-building metadata rows)
    """
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
    meshes, rows = [], []
    ways = [e for e in osm["elements"] if e["type"] == "way" and "building" in e.get("tags", {})]
    for way in sorted(ways, key=lambda w: w["id"]):
        ids = way["nodes"]
        if len(ids) < 4 or ids[0] != ids[-1] or not all(i in nodes for i in ids):
            continue  # open or incomplete outline
        latlons = [nodes[i] for i in ids[:-1]]
        if not inside(*np.mean(latlons, axis=0)):
            continue  # mostly outside the slice (beyond the terrain)
        poly = Polygon([proj.xz(*ll) for ll in latlons]).buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon" or poly.area < 4:
            continue
        tags = way["tags"]
        height = parse_height(tags)
        base = min(elev.at(*ll) for ll in latlons)
        kind = BUILDING_TYPES.get(tags.get("building", ""), "other")
        # extrude_polygon works in the XY plane extruding +Z; rotate so it extrudes up (+Y).
        # Polygon coords are (x, z), so after rotating -90° about X: X→x, Y→-z, Z→y.
        flat = Polygon([(x, -z) for x, z in poly.exterior.coords])
        m = trimesh.creation.extrude_polygon(flat, height + FOUNDATION_M)
        m.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
        m.apply_translation([0, base - FOUNDATION_M, 0])
        meshes.append(coloured(m, COLOURS[kind]))
        cx, cz = poly.centroid.x, poly.centroid.y
        rows.append({
            "osm_id": way["id"], "type": kind, "osm_building": tags.get("building"),
            "centroid": [round(cx, 2), round(cz, 2)], "height_m": round(height, 1),
            "base_m": round(base, 2), "footprint_m2": round(poly.area, 1),
            "footprint": [[round(x, 2), round(z, 2)] for x, z in poly.exterior.coords[:-1]],
        })  # fmt: skip
    return trimesh.util.concatenate(meshes), rows


def build_roads(
    osm: dict[str, Any], proj: Projection, elev: Elevation
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Drapes drivable streets over the terrain and builds a routable graph.

    Returns:
        (merged road mesh, street graph {"nodes": {...}, "edges": [...]})
    """
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
    ways = sorted(
        (e for e in osm["elements"]
         if e["type"] == "way" and e.get("tags", {}).get("highway") in ROAD_WIDTH_M),
        key=lambda w: w["id"],
    )  # fmt: skip
    # An OSM node used by more than one way (or a way's endpoint) is an intersection.
    use: dict[int, int] = {}
    for w in ways:
        for i in set(w["nodes"]):
            use[i] = use.get(i, 0) + 1
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    graph_nodes: dict[str, list[float]] = {}
    edges: list[dict[str, Any]] = []

    def point(nid: int) -> list[float]:
        """Local (x, y, z) of an OSM node, lifted slightly above the ground."""
        lat, lon = nodes[nid]
        x, z = proj.xz(lat, lon)
        return [x, elev.at(lat, lon) + ROAD_LIFT_M, z]

    # Split every way into runs of consecutive nodes inside BBOX, so streets stop
    # at the slice's edge instead of trailing off past the terrain.
    runs: list[tuple[dict[str, Any], list[int]]] = []
    for w in ways:
        run: list[int] = []
        for i in w["nodes"]:
            if i in nodes and inside(*nodes[i]):
                run.append(i)
            else:
                if len(run) > 1:
                    runs.append((w, run))
                run = []
        if len(run) > 1:
            runs.append((w, run))

    for w, ids in runs:
        tags = w["tags"]
        half = ROAD_WIDTH_M[tags["highway"]] / 2
        pts = [point(i) for i in ids]
        # Ribbon: offset each segment sideways by half the width, as quads.
        for (x0, y0, z0), (x1, y1, z1) in zip(pts, pts[1:], strict=False):
            dx, dz = x1 - x0, z1 - z0
            length = math.hypot(dx, dz) or 1.0
            ox, oz = -dz / length * half, dx / length * half
            b = len(verts)
            verts += [[x0 + ox, y0, z0 + oz], [x0 - ox, y0, z0 - oz],
                      [x1 + ox, y1, z1 + oz], [x1 - ox, y1, z1 - oz]]  # fmt: skip
            faces += [[b, b + 1, b + 2], [b + 1, b + 3, b + 2]]
        # Graph: split the way at intersections into edges.
        start = 0
        for k in range(1, len(ids)):
            if use.get(ids[k], 0) > 1 or k == len(ids) - 1:
                seg = ids[start : k + 1]
                poly = [point(i) for i in seg]
                length_m = sum(math.dist(a, b) for a, b in zip(poly, poly[1:], strict=False))
                for end in (seg[0], seg[-1]):
                    graph_nodes[str(end)] = [round(v, 2) for v in point(end)]
                edges.append({
                    "from": str(seg[0]), "to": str(seg[-1]), "name": tags.get("name", ""),
                    "class": tags["highway"], "lanes": tags.get("lanes"),
                    "oneway": tags.get("oneway") == "yes", "length_m": round(length_m, 1),
                    "polyline": [[round(v, 2) for v in p] for p in poly],
                })  # fmt: skip
                start = k
    mesh = trimesh.Trimesh(np.array(verts), np.array(faces), process=False)
    return coloured(mesh, COLOURS["road"]), {"nodes": graph_nodes, "edges": edges}


# ---------- entry point ------------------------------------------------------------


def build(out_root: Path) -> dict[str, int]:
    """Builds the SF slice into `out_root/sf-city/`.

    Returns:
        counts of buildings, street edges and street nodes written
    """
    out = out_root / "sf-city"
    cache = out / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    osm = fetch_osm(cache / "osm.json")
    elev = Elevation(cache / "terrain")
    proj = Projection()

    buildings, rows = build_buildings(osm, proj, elev)
    roads, graph = build_roads(osm, proj, elev)
    scene = trimesh.Scene()
    for name, mesh, flat in (
        ("terrain", terrain_mesh(proj, elev), False),
        ("water", water_plane(proj), True),
        ("roads", roads, True),
        ("buildings", buildings, True),
    ):
        scene.add_geometry(finalize(mesh, flat), node_name=name, geom_name=name)
    # Normals are required for lit materials; without them three.js renders black.
    (out / "sf-city.glb").write_bytes(scene.export(file_type="glb", include_normals=True))

    s, w, n, e = BBOX
    (out / "buildings.json").write_text(json.dumps(rows, indent=1, sort_keys=True))
    (out / "streets.json").write_text(json.dumps(graph, indent=1, sort_keys=True))
    (out / "meta.json").write_text(json.dumps({
        "area": "San Francisco: SoMa, Financial District, Embarcadero",
        "bbox_wgs84": {"south": s, "west": w, "north": n, "east": e},
        "origin_wgs84": [proj.lat0, proj.lon0],
        "axes": "metres; x = east, y = up (above sea level), z = south (north is -z)",
        "water_level_m": WATER_LEVEL_M,
        "attribution": [
            "Map data © OpenStreetMap contributors, available under the Open Database "
            "License (ODbL 1.0): https://www.openstreetmap.org/copyright",
            "Elevation: AWS Terrain Tiles (Mapzen, terrarium encoding), derived from "
            "USGS 3DEP (public domain): https://registry.opendata.aws/terrain-tiles/",
        ],
        "notes": "Building names are omitted on purpose (the game uses parody names).",
    }, indent=2))  # fmt: skip
    counts = {"buildings": len(rows), "street_edges": len(graph["edges"]),
              "street_nodes": len(graph["nodes"])}  # fmt: skip
    print(f"sf-city: {counts} -> {out}")
    return counts
