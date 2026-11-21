"""Downloads the curated sounds, particle sprites and fonts into the asset dataset.

Reads `scripts/media_sources.json` and writes, under the staging folder
(`config.MIRROR_DIR`):

    audio-opengameart/<id>/<files>, info.json     single sounds and loops
    audio-freesound/<id>/<id>.mp3, info.json      sirens, crashes, traffic, horn
    kenney-media/<pack>/<files>, info.json        Kenney audio and particle packs
    google-fonts/<family>/<file>.ttf, OFL.txt, info.json

Each `info.json` records what the item is, its source page, author, licence and
a sha256 per file. `buildoff assets dataset` turns those into each folder's
LICENSE.md and ATTRIBUTION.md (`harness.dataset.media_docs`), so CC-BY credits
can't drift from what was actually downloaded. Called by `buildoff assets media`.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from harness.assets import kenney_zip
from harness.config import MIRROR_DIR, REPO_ROOT
from harness.textures import get, write_checked

PLAN_PATH: Path = REPO_ROOT / "scripts" / "media_sources.json"
OGA_FILES: str = "https://opengameart.org/sites/default/files"
OGA_PAGE: str = "https://opengameart.org/content"
FREESOUND_PREVIEWS: str = "https://cdn.freesound.org/previews"


def write_info(folder: Path, record: dict[str, Any]) -> None:
    """Writes an item's info.json with stable key order (deterministic rebuilds)."""
    (folder / "info.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def unzip_kept(archive: zipfile.ZipFile, prefixes: list[str], dest: Path) -> dict[str, str]:
    """Extracts the archive members under any of `prefixes` into `dest`.

    Paths keep everything after the matched prefix; with several prefixes, each
    file also keeps the prefix's last folder (`footsteps/boots/0.ogg` -> `boots/0.ogg`).
    macOS resource forks (`__MACOSX/`, `._*`) are skipped.

    Returns:
        {relative path: sha256} for every file written
    """
    hashes: dict[str, str] = {}
    for name in sorted(archive.namelist()):
        if name.endswith("/") or "__MACOSX" in name or Path(name).name.startswith("._"):
            continue
        prefix = next((p for p in prefixes if name.startswith(p)), None)
        if prefix is None:
            continue
        rel = name.removeprefix(prefix)
        # Keep the surface/category folder for multi-prefix zips (footsteps/boots/...).
        if len(prefixes) > 1:
            rel = f"{Path(prefix).name}/{rel}"
        hashes[rel] = write_checked(dest / rel, archive.read(name))
    if not hashes:
        raise ValueError(f"no files matched {prefixes} in the archive")
    return hashes


def fetch_opengameart(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each OpenGameArt item's files (or the kept part of its zip).

    Returns:
        the info records written
    """
    records = []
    for item_id, item in sorted(spec["items"].items()):
        dest = out / item_id
        if "zip" in item:
            archive = zipfile.ZipFile(io.BytesIO(get(f"{OGA_FILES}/{item['zip']}")))
            files = unzip_kept(archive, item["zip_keep"], dest)
        else:
            files = {
                name: write_checked(dest / name, get(f"{OGA_FILES}/{name}"))
                for name in item["files"]
            }
        record = {
            "id": item_id,
            "what": item["what"],
            "author": item["author"],
            "license": item["license"],
            "source": f"{OGA_PAGE}/{item['page']}",
            "files": files,
        }
        if "license_note" in item:
            record["license_note"] = item["license_note"]
        write_info(dest, record)
        records.append(record)
        print(f"opengameart {item_id}: {len(files)} files")
    return records


def fetch_freesound(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each Freesound item's high-quality preview (MP3) with an info.json.

    Returns:
        the info records written
    """
    records = []
    for item_id, item in sorted(spec["items"].items()):
        name = f"{item_id}.mp3"
        data = get(f"{FREESOUND_PREVIEWS}/{item['preview']}-hq.mp3")
        record = {
            "id": item_id,
            "what": item["what"],
            "author": item["author"],
            "license": item["license"],
            "source": f"https://freesound.org/s/{item['sound_id']}/",
            "files": {name: write_checked(out / item_id / name, data)},
            "license_note": "Freesound HQ preview (MP3); the original is on the source page.",
        }
        write_info(out / item_id, record)
        records.append(record)
        print(f"freesound {item_id}")
    return records


def fetch_kenney(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each Kenney pack and keeps its audio or sprite folder plus License.txt.

    Returns:
        the info records written
    """
    records = []
    for slug, item in sorted(spec["items"].items()):
        archive = kenney_zip(slug)
        files = unzip_kept(archive, [item["keep_prefix"]], out / slug)
        files["License.txt"] = write_checked(
            out / slug / "License.txt", archive.read("License.txt")
        )
        record = {
            "id": slug,
            "what": item["what"],
            "author": "Kenney (www.kenney.nl)",
            "license": "CC0-1.0",
            "source": f"https://kenney.nl/assets/{slug}",
            "files": files,
        }
        write_info(out / slug, record)
        records.append(record)
        print(f"kenney {slug}: {len(files)} files")
    return records


def fetch_google_fonts(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each font family's files and its OFL.txt at the pinned google/fonts commit.

    Returns:
        the info records written
    """
    raw = f"https://raw.githubusercontent.com/{spec['repo']}/{spec['revision']}/ofl"
    records = []
    for family, item in sorted(spec["items"].items()):
        names = [*item["files"], "OFL.txt"]
        files = {n: write_checked(out / family / n, get(f"{raw}/{family}/{n}")) for n in names}
        record = {
            "id": family,
            "what": item["what"],
            "author": "see OFL.txt (copyright line)",
            "license": "OFL-1.1",
            "source": f"https://github.com/{spec['repo']}/tree/{spec['revision']}/ofl/{family}",
            "files": files,
        }
        write_info(out / family, record)
        records.append(record)
        print(f"font {family}: {len(files)} files")
    return records


def build(root: Path = MIRROR_DIR) -> dict[str, int]:
    """Downloads every curated sound, particle pack and font into the staging folder.

    Returns:
        items written per folder
    """
    plan = json.loads(PLAN_PATH.read_text())
    steps = [
        ("opengameart", fetch_opengameart),
        ("freesound", fetch_freesound),
        ("kenney", fetch_kenney),
        ("google_fonts", fetch_google_fonts),
    ]
    return {
        plan[key]["folder"]: len(fetcher(plan[key], root / plan[key]["folder"]))
        for key, fetcher in steps
    }
