"""Downloads the curated CC0 skies and surface textures into the asset dataset.

Reads `scripts/texture_sources.json` and writes, under the staging folder
(`config.MIRROR_DIR`):

    polyhaven-hdris/<id>/<id>_1k.hdr, <id>_2k.hdr, info.json
    polyhaven-textures/<id>/<id>_<map>_1k.jpg ..., info.json
    ambientcg-textures/<id>/<id>_1K-JPG_<Map>.jpg ..., info.json

Each `info.json` records what the item is, its real-world size in metres (so a
game can set `texture.repeat`), which file is which map, the source page, the
licence, and a sha256 of every file. Poly Haven downloads are checked against
the md5 its API publishes; ambientCG publishes no checksums, so its files are
only hashed for the record.

Both sources are CC0. Poly Haven asks API users to set a descriptive
User-Agent, which `USER_AGENT` does. Called by `buildoff assets textures`.
"""

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from harness.assets import safe_join
from harness.config import MIRROR_DIR, REPO_ROOT

PLAN_PATH: Path = REPO_ROOT / "scripts" / "texture_sources.json"
USER_AGENT: str = (
    "grand-theft-gpu-asset-builder/0.1 (+https://github.com/harpreetsahota204/grand-theft-gpu)"
)
POLYHAVEN_API: str = "https://api.polyhaven.com"
AMBIENTCG_API: str = "https://ambientcg.com/api/v2/full_json"


def get(url: str) -> bytes:
    """Downloads a URL with the project's User-Agent (also used by `harness.media`)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def get_json(url: str) -> Any:
    """Downloads and parses a JSON document."""
    return json.loads(get(url))


def write_checked(path: Path, data: bytes, md5: str | None = None) -> str:
    """Writes a downloaded file, verifying its md5 when the source publishes one.

    Raises:
        ValueError: if the md5 doesn't match (a corrupted or changed upstream file)

    Returns:
        the file's hex sha256 (recorded in info.json)
    """
    if md5 and hashlib.md5(data).hexdigest() != md5:
        raise ValueError(f"md5 mismatch for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def polyhaven_size_m(asset_id: str) -> list[float] | None:
    """Real-world size of a Poly Haven texture in metres ([w, h]), from its mm dimensions."""
    info = get_json(f"{POLYHAVEN_API}/info/{asset_id}")
    dims = info.get("dimensions")
    return [round(dims[0] / 1000, 3), round(dims[1] / 1000, 3)] if dims else None


def fetch_polyhaven_hdris(spec: dict[str, Any], out: Path) -> int:
    """Downloads each HDRI at the listed resolutions (.hdr) with an info.json.

    Returns:
        items written
    """
    for asset_id, what in spec["items"].items():
        files = get_json(f"{POLYHAVEN_API}/files/{asset_id}")["hdri"]
        record: dict[str, Any] = {"id": asset_id, "what": what, "files": {}}
        for res in spec["resolutions"]:
            meta = files[res]["hdr"]
            name = f"{asset_id}_{res}.hdr"
            digest = write_checked(out / asset_id / name, get(meta["url"]), meta.get("md5"))
            record["files"][res] = {"file": name, "sha256": digest, "bytes": meta["size"]}
        record.update(
            source=f"https://polyhaven.com/a/{asset_id}",
            author="Poly Haven",
            license="CC0-1.0",
            seeded_resolution=spec["seeded_resolution"],
        )
        (out / asset_id / "info.json").write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"hdri {asset_id}")
    return len(spec["items"])


def fetch_polyhaven_textures(spec: dict[str, Any], out: Path) -> int:
    """Downloads each texture's selected maps (jpg) with an info.json.

    Returns:
        items written
    """
    res = spec["resolution"]
    for asset_id, what in spec["items"].items():
        files = get_json(f"{POLYHAVEN_API}/files/{asset_id}")
        record: dict[str, Any] = {"id": asset_id, "what": what, "maps": {}}
        for upstream, role in spec["maps"].items():
            if upstream not in files:
                continue  # not every texture has every map (e.g. no AO)
            meta = files[upstream][res]["jpg"]
            name = f"{asset_id}_{role}_{res}.jpg"
            digest = write_checked(out / asset_id / name, get(meta["url"]), meta.get("md5"))
            record["maps"][role] = {"file": name, "sha256": digest}
        record.update(
            size_m=polyhaven_size_m(asset_id),
            source=f"https://polyhaven.com/a/{asset_id}",
            author="Poly Haven",
            license="CC0-1.0",
        )
        (out / asset_id / "info.json").write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"texture {asset_id}")
    return len(spec["items"])


def fetch_ambientcg(spec: dict[str, Any], out: Path) -> int:
    """Downloads each ambientCG material zip and keeps the selected maps.

    Returns:
        items written
    """
    res = spec["resolution"]
    for asset_id, what in spec["items"].items():
        meta = get_json(f"{AMBIENTCG_API}?id={asset_id}&include=dimensionsData")["foundAssets"][0]
        archive = zipfile.ZipFile(
            io.BytesIO(get(f"https://ambientcg.com/get?file={asset_id}_{res}.zip"))
        )
        record: dict[str, Any] = {"id": asset_id, "what": what, "maps": {}}
        for name in sorted(archive.namelist()):
            # Files look like "Facade018C_1K-JPG_Color.jpg"; the suffix is the map.
            role = Path(name).stem.split("_")[-1]
            if role in spec["keep_maps"] and name.endswith(".jpg"):
                data = archive.read(name)
                record["maps"][role] = {
                    "file": name,
                    "sha256": write_checked(safe_join(out / asset_id, name), data),
                }
        dims = meta.get("dimensionX"), meta.get("dimensionY")
        record.update(
            # ambientCG dimensions are in centimetres when present.
            size_m=[round(dims[0] / 100, 2), round(dims[1] / 100, 2)] if all(dims) else None,
            source=f"https://ambientcg.com/view?id={asset_id}",
            author="ambientCG",
            license="CC0-1.0",
        )
        (out / asset_id / "info.json").write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"ambientcg {asset_id}")
    return len(spec["items"])


def build(root: Path = MIRROR_DIR) -> dict[str, int]:
    """Downloads every curated sky and texture into the staging folder.

    Returns:
        items written per folder
    """
    plan = json.loads(PLAN_PATH.read_text())
    return {
        "polyhaven-hdris": fetch_polyhaven_hdris(plan["polyhaven_hdris"], root / "polyhaven-hdris"),
        "polyhaven-textures": fetch_polyhaven_textures(
            plan["polyhaven_textures"], root / "polyhaven-textures"
        ),
        "ambientcg-textures": fetch_ambientcg(
            plan["ambientcg_textures"], root / "ambientcg-textures"
        ),
    }
