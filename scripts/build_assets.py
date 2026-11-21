"""Rebuilds everything in `assets/` from its original sources.

This is the replication path: someone with a fresh clone runs one command and
gets the exact asset set both race contenders build with. It downloads:

- `gpu`: the CC0 graphics card from Grab3D (direct file URLs)
- `cars`: Kenney Car Kit (CC0). Kenney hides the zip behind a donation popup;
  the page's own "continue without donating" flow fetches a signed URL from
  `/download-link/<id>` using the page's session cookie, so we do the same.
- `props`: the curated NVIDIA USDCraft-10K props listed in
  `scripts/usdcraft_props.csv`, downloaded from Hugging Face and converted to
  `.glb` by `scripts/convert_usdcraft.py` running inside Blender

Usage (from the repo root):
    uv run python scripts/build_assets.py all
    uv run python scripts/build_assets.py props --out /tmp/assets

Blender is found at `$BLENDER`, else the default macOS install path.
"""

import argparse
import csv
import http.cookiejar
import io
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
PROPS_CSV: Path = REPO_ROOT / "scripts" / "usdcraft_props.csv"
CONVERTER: Path = REPO_ROOT / "scripts" / "convert_usdcraft.py"
DEFAULT_BLENDER: str = "/Applications/Blender.app/Contents/MacOS/Blender"

GPU_BASE_URL: str = "https://grab3d.com/dl/graphics-card"
GPU_FILES: tuple[str, ...] = ("graphics-card-light.glb", "LICENSE.txt", "manifest.json")

KENNEY_PAGE: str = "https://kenney.nl/assets/car-kit"
# Hex of "assets/car-kit": the id the page passes to its download endpoint.
KENNEY_DOWNLOAD_ID: str = "6173736574732f6361722d6b6974"
USDCRAFT_REPO: str = "nvidia/USDCraft-10K"

# Kenney rejects urllib's default user agent.
USER_AGENT: str = "Mozilla/5.0 (asset-rebuild script)"


def fetch(url: str, opener: urllib.request.OpenerDirector | None = None) -> bytes:
    """Downloads a URL and returns its body.

    Args:
        url: what to fetch
        opener: an opener carrying cookies, when the site needs a session

    Returns:
        the response body
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": KENNEY_PAGE})
    with (opener or urllib.request.build_opener()).open(req, timeout=120) as resp:
        return resp.read()


def build_gpu(out: Path) -> None:
    """Downloads the CC0 graphics card model, its license and manifest into `out/gpu`."""
    dest = out / "gpu"
    dest.mkdir(parents=True, exist_ok=True)
    for name in GPU_FILES:
        (dest / name).write_bytes(fetch(f"{GPU_BASE_URL}/{name}"))
    print(f"gpu: {len(GPU_FILES)} files -> {dest}")


def build_cars(out: Path) -> None:
    """Downloads Kenney Car Kit and keeps the GLBs, their shared texture and the license.

    Args:
        out: assets root; files land in `out/cars`
    """
    # Visiting the page first sets the session cookie the download endpoint checks.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    fetch(KENNEY_PAGE, opener)
    signed = json.loads(fetch(f"https://kenney.nl/download-link/{KENNEY_DOWNLOAD_ID}", opener))
    archive = zipfile.ZipFile(io.BytesIO(fetch(signed["url"], opener)))

    dest = out / "cars"
    (dest / "Textures").mkdir(parents=True, exist_ok=True)
    kept = 0
    for name in archive.namelist():
        # GLBs reference Textures/colormap.png relative to themselves, so keep
        # that layout; skip the kit's FBX/OBJ copies and previews.
        if name.startswith("Models/GLB format/") and not name.endswith("/"):
            rel = name.removeprefix("Models/GLB format/")
            (dest / rel).write_bytes(archive.read(name))
            kept += 1
        elif name in ("License.txt", "Preview.png"):
            (dest / name).write_bytes(archive.read(name))
            kept += 1
    print(f"cars: {kept} files -> {dest}")


def build_props(out: Path) -> None:
    """Downloads the curated USDCraft props and converts them to `.glb` with Blender.

    Args:
        out: assets root; files land in `out/props`
    """
    blender = os.environ.get("BLENDER", DEFAULT_BLENDER)
    if not Path(blender).exists():
        raise SystemExit(f"Blender not found at {blender}; set $BLENDER or install it")

    with PROPS_CSV.open() as f:
        folders = [row["path"] for row in csv.DictReader(f)]

    with tempfile.TemporaryDirectory(prefix="usdcraft-") as raw:
        # Only the curated folders (~120 MB), not the whole 10K-object dataset.
        snapshot_download(
            repo_id=USDCRAFT_REPO,
            repo_type="dataset",
            allow_patterns=[f"{p}/*" for p in folders],
            local_dir=raw,
        )
        subprocess.run(
            [
                blender,
                "-b",
                "--factory-startup",
                "--python",
                str(CONVERTER),
                "--",
                str(PROPS_CSV),
                raw,
                str(out / "props"),
            ],
            check=True,
        )
    shutil.copy(REPO_ROOT / "assets" / "props" / "NOTICE.md", out / "props" / "NOTICE.md")
    print(f"props: {len(folders)} converted -> {out / 'props'}")


BUILDERS = {"gpu": build_gpu, "cars": build_cars, "props": build_props}


def main() -> None:
    """Parses the CLI and runs the requested builders."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("what", choices=[*BUILDERS, "all"], help="which asset set to rebuild")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "assets", help="assets root")
    a = p.parse_args()
    for name, build in BUILDERS.items():
        if a.what in (name, "all"):
            build(a.out)


if __name__ == "__main__":
    main()
