# sf-city: attribution

**What:** A real slice of San Francisco (SoMa → Financial District → Embarcadero,
about 1.6 × 2.3 km) built for a browser game. It includes the terrain with its hills, 2,168
buildings extruded to their real heights, drivable streets draped over the ground, the bay,
and a routable street graph.

| File | What | License |
|---|---|---|
| `sf-city.glb` | Terrain, buildings, streets and water as one glTF scene (metres, y up) | Produced Work from OpenStreetMap data; credit as below |
| `buildings.json` | Per building: footprint, height, base elevation, OSM type. **No names.** | ODbL 1.0 (a derivative database) |
| `streets.json` | Street graph: intersections, segments (name, class, lanes, one-way, length, polyline) | ODbL 1.0 (a derivative database) |
| `meta.json` | Bounding box, origin, axes, attribution | ODbL 1.0 |
| `_cache/osm.json` | The exact OpenStreetMap snapshot this was built from | ODbL 1.0 |
| `_cache/terrain/*.png` | The elevation tiles used | See elevation, below |

## Map data: OpenStreetMap

**Map data © OpenStreetMap contributors**, available under the
[Open Database License (ODbL) 1.0](https://www.openstreetmap.org/copyright). The license text
is in `LICENSE-ODbL.txt`.

`buildings.json`, `streets.json` and the cached snapshot are **derivative databases**. If you
publicly use a modified version of them, ODbL requires you to share it under ODbL too.
`sf-city.glb` is a **Produced Work**: you may use it freely as long as you credit
"© OpenStreetMap contributors".

## Elevation

[AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (Mapzen, terrarium
encoding). In the United States the source is USGS 3DEP, which is public domain. Credit:
"Elevation data: Mapzen / AWS Terrain Tiles, USGS 3DEP."

## What we changed

The data came from the Overpass API and was converted with `harness/sfcity.py` in
[grand-theft-gpu](https://github.com/harpreetsahota204/grand-theft-gpu) (`buildoff assets city`):

* Buildings: simple closed outlines only, height from `height`, then `building:levels` × 3.2 m,
  then a 10 m default. They sit on the terrain and sink 2 m below their lowest corner.
* **Building names were dropped on purpose.** OSM names many towers after companies, and the
  game this was made for uses parody names only.
* Streets: drivable classes only, clipped at the area's edge, with a width per class.
* The street graph splits each OSM way at intersections.
