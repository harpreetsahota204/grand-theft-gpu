"""Downloads the curated sounds, particle sprites and fonts into the asset dataset.

Reads `scripts/media_sources.json` and writes, under the staging folder
(`config.MIRROR_DIR`):

    audio-opengameart/<id>/<files>, info.json     single sounds and loops
    kenney-media/<pack>/<files>, info.json        Kenney audio and particle packs
    google-fonts/<family>/<file>.ttf, OFL.txt, info.json

Each `info.json` records what the item is, its source page, author, licence and
a sha256 per file. Each folder also gets a LICENSE.md and an ATTRIBUTION.md
generated from the same plan, so CC-BY credits can't drift from what was
actually downloaded. Called by `buildoff assets media`.
"""

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from harness.assets import kenney_zip
from harness.config import MIRROR_DIR, REPO_ROOT

PLAN_PATH: Path = REPO_ROOT / "scripts" / "media_sources.json"
OGA_FILES: str = "https://opengameart.org/sites/default/files"
OGA_PAGE: str = "https://opengameart.org/content"
# OpenGameArt rejects urllib's default user agent.
USER_AGENT: str = (
    "grand-theft-gpu-asset-builder/0.1 (+https://github.com/harpreetsahota204/grand-theft-gpu)"
)
LICENSE_URLS: dict[str, str] = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "OFL-1.1": "https://openfontlicense.org",
}


def get(url: str) -> bytes:
    """Downloads a URL with the project's User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def save(path: Path, data: bytes) -> str:
    """Writes a file (creating folders) and returns its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_info(folder: Path, record: dict[str, Any]) -> None:
    """Writes an item's info.json with stable key order (deterministic rebuilds)."""
    (folder / "info.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def unzip_kept(archive: zipfile.ZipFile, prefixes: list[str], dest: Path) -> dict[str, str]:
    """Extracts the archive members under any of `prefixes` into `dest`.

    Paths keep everything after the matched prefix. macOS resource forks
    (`__MACOSX/`, `._*`) are skipped.

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
        rel = name.removeprefix(prefix) or Path(name).name
        # Keep the surface/category folder for multi-prefix zips (footsteps/boots/...).
        if len(prefixes) > 1:
            rel = f"{Path(prefix).name}/{rel}"
        hashes[rel] = save(dest / rel, archive.read(name))
    if not hashes:
        raise ValueError(f"no files matched {prefixes} in the archive")
    return hashes


def fetch_opengameart(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each OpenGameArt item's files (or the kept part of its zip).

    Returns:
        the info records written, for the folder's ATTRIBUTION.md
    """
    records = []
    for item_id, item in sorted(spec["items"].items()):
        dest = out / item_id
        if "zip" in item:
            archive = zipfile.ZipFile(io.BytesIO(get(f"{OGA_FILES}/{item['zip']}")))
            files = unzip_kept(archive, item["zip_keep"], dest)
        else:
            files = {name: save(dest / name, get(f"{OGA_FILES}/{name}")) for name in item["files"]}
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


def fetch_kenney(spec: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    """Downloads each Kenney pack and keeps its audio or sprite folder plus License.txt.

    Returns:
        the info records written
    """
    records = []
    for slug, item in sorted(spec["items"].items()):
        archive = kenney_zip(slug)
        files = unzip_kept(archive, [item["keep_prefix"]], out / slug)
        files["License.txt"] = save(out / slug / "License.txt", archive.read("License.txt"))
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
        files = {n: save(out / family / n, get(f"{raw}/{family}/{n}")) for n in names}
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


def write_folder_docs(out: Path, title: str, records: list[dict[str, Any]]) -> None:
    """Writes a folder's LICENSE.md (licences used) and ATTRIBUTION.md (per-item credits).

    Args:
        out: the dataset folder, e.g. MIRROR_DIR / "audio-opengameart"
        title: human name for the folder, used as the heading
        records: the info records of every item in the folder
    """
    licenses = sorted({r["license"] for r in records})
    lines = [f"# {title}: licences", ""]
    lines += [f"- {lic}: {LICENSE_URLS[lic]}" for lic in licenses]
    lines += ["", "Which item uses which licence is listed in ATTRIBUTION.md and each info.json."]
    (out / "LICENSE.md").write_text("\n".join(lines) + "\n")

    rows = [f"# {title}: attribution", "", "| Item | What | Author | Licence | Source |"]
    rows.append("|---|---|---|---|---|")
    for r in records:
        rows.append(f"| {r['id']} | {r['what']} | {r['author']} | {r['license']} | {r['source']} |")
    notes = [f"- {r['id']}: {r['license_note']}" for r in records if "license_note" in r]
    if notes:
        rows += ["", "Notes:", "", *notes]
    (out / "ATTRIBUTION.md").write_text("\n".join(rows) + "\n")


def build(root: Path = MIRROR_DIR) -> dict[str, int]:
    """Downloads every curated sound, particle pack and font into the staging folder.

    Returns:
        items written per folder
    """
    plan = json.loads(PLAN_PATH.read_text())
    steps = [
        ("opengameart", "OpenGameArt sounds", fetch_opengameart),
        ("kenney", "Kenney audio and particles", fetch_kenney),
        ("google_fonts", "Google Fonts", fetch_google_fonts),
    ]
    counts = {}
    for key, title, fetcher in steps:
        out = root / plan[key]["folder"]
        records = fetcher(plan[key], out)
        write_folder_docs(out, title, records)
        counts[plan[key]["folder"]] = len(records)
    return counts
