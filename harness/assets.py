"""Rebuilds everything in `assets/` from its original sources.

This is the replication path: someone with a fresh clone runs one command and
gets the exact asset set both race contenders build with. It downloads:

- `gpu`: the CC0 graphics card from Grab3D (direct file URLs)
- `cars`: Kenney Car Kit (CC0), via `kenney_zip`
- `props`: the curated NVIDIA USDCraft-10K props listed in
  `scripts/usdcraft_props.csv`, downloaded from Hugging Face and converted to
  `.glb` by `scripts/convert_usdcraft.py` running inside Blender

Called by `buildoff assets` (see `harness.cli`):
    uv run buildoff assets all
    uv run buildoff assets props --out /tmp/assets

Blender is found at `$BLENDER`, else the default macOS install path.
"""

import csv
import hashlib
import http.cookiejar
import io
import json
import os
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download

from harness.config import DEFAULT_BLENDER, REPO_ROOT

PROPS_CSV: Path = REPO_ROOT / "scripts" / "usdcraft_props.csv"
CONVERTER: Path = REPO_ROOT / "scripts" / "convert_usdcraft.py"

GPU_BASE_URL: str = "https://grab3d.com/dl/graphics-card"
# sha256 of each GPU file as first downloaded; a rebuild refuses a changed upstream.
GPU_FILES: dict[str, str] = {
    "graphics-card-light.glb": "8d6c2a72d0c6d4391150d0b013826b055867bd539c1ab4f845d07f07a202ec74",
    "LICENSE.txt": "01908a56d6cada52704b20c5094c2aa16c9d8be6f124349c986764067abfd921",
    "manifest.json": "d3113d1b1c1a63a5e07ccf7004fd9b0d43d6f1671ee2cd232fc3d4e52be9257f",
}

KENNEY_CAR_KIT: str = "car-kit"
# sha256 of the car-kit zip (verified 2026-11-21 to match every GLB in the pack).
KENNEY_CAR_KIT_SHA256: str = "fac7dacac5c7874348cf19729af3ef205f3d366493edaf0a827d93f4fdf3d0c4"
USDCRAFT_REPO: str = "nvidia/USDCraft-10K"
# The dataset revision the props were converted from (last modified 2026-11-19,
# before the props were added on 2026-11-20).
USDCRAFT_REVISION: str = "9265e910275b28e1317893141e1a838da9e657c1"

PROPS_NOTICE: str = """\
# USDCraft-10K props: attribution

The `.glb` files in this folder are derived from **NVIDIA USDCraft-10K**
(https://huggingface.co/datasets/nvidia/USDCraft-10K), licensed under the
**Apache License 2.0** (https://www.apache.org/licenses/LICENSE-2.0).

**Modifications:** converted from OpenUSD (`physx/model.usdc`) to glTF binary
with `scripts/convert_usdcraft.py`. Collision meshes were removed, meshes over
4,000 triangles were decimated, and the axes were converted from Z-up to Y-up.
Joint data was extracted into `manifest.json`.

`manifest.json` lists the source object ID and dataset path for every file.
"""

# Kenney rejects urllib's default user agent.
USER_AGENT: str = "Mozilla/5.0 (asset-rebuild script)"


def fetch(
    url: str, opener: urllib.request.OpenerDirector | None = None, referer: str = ""
) -> bytes:
    """Downloads a URL and returns its body.

    Args:
        url: what to fetch
        opener: an opener carrying cookies, when the site needs a session
        referer: Referer header, for sites that check where a download came from

    Returns:
        the response body
    """
    headers = {"User-Agent": USER_AGENT} | ({"Referer": referer} if referer else {})
    req = urllib.request.Request(url, headers=headers)
    with (opener or urllib.request.build_opener()).open(req, timeout=120) as resp:
        return resp.read()


def verify(data: bytes, sha256: str, what: str) -> bytes:
    """Returns data unchanged if its sha256 matches, so a changed upstream can't slip in.

    Raises:
        ValueError: on a mismatch
    """
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        raise ValueError(f"{what}: sha256 {actual} != pinned {sha256} (upstream changed?)")
    return data


def safe_join(root: Path, rel: str) -> Path:
    """Joins an archive member's name onto root, refusing paths that escape it.

    Archive member names come from third parties; one like `../../.zshrc`
    must not write outside the staging folder (zip-slip).

    Raises:
        ValueError: if the result isn't inside root
    """
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"archive member escapes {root}: {rel!r}")
    return target


def build_gpu(out: Path) -> None:
    """Downloads the CC0 graphics card model, its license and manifest into `out/gpu`."""
    dest = out / "gpu"
    dest.mkdir(parents=True, exist_ok=True)
    for name, sha in GPU_FILES.items():
        (dest / name).write_bytes(verify(fetch(f"{GPU_BASE_URL}/{name}"), sha, f"gpu/{name}"))
    print(f"gpu: {len(GPU_FILES)} files -> {dest}")


def kenney_zip(slug: str, sha256: str | None = None) -> zipfile.ZipFile:
    """Downloads one Kenney asset pack (CC0) as an in-memory zip.

    Kenney hides the zip behind a donation popup; the page's own "continue
    without donating" flow fetches a signed URL from `/download-link/<id>`
    using the page's session cookie, so we do the same.

    Args:
        slug: the pack's page name, e.g. "car-kit" for kenney.nl/assets/car-kit
        sha256: the zip's pinned hash, checked when given
    """
    page = f"https://kenney.nl/assets/{slug}"
    # Visiting the page first sets the session cookie the download endpoint checks.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    fetch(page, opener, page)
    # The download id is just the hex of "assets/<slug>".
    link_id = f"assets/{slug}".encode().hex()
    signed = json.loads(fetch(f"https://kenney.nl/download-link/{link_id}", opener, page))
    data = fetch(signed["url"], opener, page)
    if sha256:
        verify(data, sha256, f"kenney {slug}")
    return zipfile.ZipFile(io.BytesIO(data))


def build_cars(out: Path) -> None:
    """Downloads Kenney Car Kit and keeps the GLBs, their shared texture and the license.

    Args:
        out: assets root; files land in `out/cars`
    """
    archive = kenney_zip(KENNEY_CAR_KIT, KENNEY_CAR_KIT_SHA256)
    dest = out / "cars"
    (dest / "Textures").mkdir(parents=True, exist_ok=True)
    kept = 0
    for name in archive.namelist():
        # GLBs reference Textures/colormap.png relative to themselves, so keep
        # that layout; skip the kit's FBX/OBJ copies and previews.
        if name.startswith("Models/GLB format/") and not name.endswith("/"):
            rel = name.removeprefix("Models/GLB format/")
            target = safe_join(dest, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
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
            revision=USDCRAFT_REVISION,
            allow_patterns=[f"{p}/*" for p in folders],
            local_dir=raw,
        )
        subprocess.run(
            [
                blender,
                "-b",
                "--factory-startup",
                # Without this, Blender exits 0 even when the script raises.
                "--python-exit-code",
                "1",
                "--python",
                str(CONVERTER),
                "--",
                str(PROPS_CSV),
                raw,
                str(out / "props"),
            ],
            check=True,
        )
    # Written from the constant: assets/ isn't in git, and copying assets/props
    # onto itself (the default --out) would raise SameFileError.
    (out / "props" / "NOTICE.md").write_text(PROPS_NOTICE)
    print(f"props: {len(folders)} converted -> {out / 'props'}")


BUILDERS = {"gpu": build_gpu, "cars": build_cars, "props": build_props}


def build(what: str, out: Path) -> None:
    """Rebuilds one asset set, or all of them, into `out`.

    Args:
        what: "gpu", "cars", "props" or "all"
        out: assets root; each set lands in its own subfolder
    """
    for name, builder in BUILDERS.items():
        if what in (name, "all"):
            builder(out)
