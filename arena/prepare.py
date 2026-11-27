"""Packages two race contenders' Vite `dist/` bundles for the blind HF Space arena.

Run locally from the repo root before testing or uploading `arena/` to Hugging
Face Spaces:

    uv run python arena/prepare.py --race-id v15-full-100usd-001 --link-local-assets

Responsibilities:
- Copies `kimi/workspace/dist` and `opus/workspace/dist` into opaque folders
  under `arena/builds/<opaque-id>/` so directory names never hint at contenders.
- Strips `assets/gt-gpu/` (~650 MB per side) so shared assets stream once from
  the pinned Hugging Face dataset CDN (with an optional local symlink for offline
  testing).
- Scans every non-media file (and flags source maps) for leaked model/vendor names (`kimi`, `opus`,
  `claude`, `anthropic`, `fireworks`, `moonshot`) and scrubs `<title>` leaks. Parody place
  names on `LEAK_ALLOWLIST` are exempt: they contain a vendor token by coincidence.
- Strips Vite content hashes from bundle names (`index-<hash>.js` -> `index.js`) so
  file names don't tell the two builds apart.
- Writes `arena/builds/manifest.json`, which stays server-side in `arena/app.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict


class BuildMeta(TypedDict):
    """Per-build entry written into `arena/builds/manifest.json`."""

    contender: str
    label: str
    size_mb: float


class ArenaManifest(TypedDict):
    """Server-side manifest written by `package_race` and read by `arena/app.py`."""

    race_id: str
    hf_assets_repo: str
    hf_assets_revision: str
    builds: dict[str, BuildMeta]


# Defaults mirror harness/config.py so prepare.py works standalone as well as in-repo.
DEFAULT_RUNS_ROOT: Path = Path.home() / "gta-race-runs"
DEFAULT_HF_ASSETS_REPO: str = "harpreetsahota/grand-theft-gpu-assets"
DEFAULT_HF_ASSETS_REVISION: str = "0d543859f7bea8a088b5d659b19fb7bdc7b9e518"

# Human-readable labels revealed ONLY after a visitor submits their blind ballot.
CONTENDER_LABELS: dict[str, str] = {
    "kimi": "Kimi K3.1 Pro",
    "opus": "Claude Opus 5.5",
}

# Case-insensitive word-boundary patterns that must not leak contender identity.
# Also catches camelCase in minified code (`claudeMode`, `useOpus`) while skipping
# substrings of other words (`libopus`, `Claudette`): a name may start at a word start or at
# a lowercase-to-uppercase boundary, and must not run on into more lowercase letters.
LEAK_PATTERN: re.Pattern[str] = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?i:kimi|moonshot|opus|claude|anthropic|fireworks)"
    r"(?![a-z])"
)

# Exact phrases that contain a vendor token but reveal nothing about the builder. They are
# matched whole and case-insensitively: "Moonshot Alley" is a street in the parody city, not
# a Kimi credit, and hiding only these characters still reports a real token in the same file.
LEAK_ALLOWLIST: frozenset[str] = frozenset({"moonshot alley"})

# Binary media skipped by the leak scan: their bytes hold codec tags such as `OpusHead`
# (Ogg Opus audio) or random byte runs (3D models) that are not identity leaks.
# Everything else is scanned as text.
SKIP_SCAN_SUFFIXES: frozenset[str] = frozenset(
    {
        ".ogg",
        ".opus",
        ".mp3",
        ".wav",
        ".m4a",
        ".webm",
        ".mp4",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".ktx2",
        ".fbx",
        ".glb",
        ".bin",
        ".hdr",
        ".exr",
        ".basis",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    }
)

# Shared dataset folder inside dist/ stripped during packaging to avoid 1.3 GB bloat.
SHARED_ASSETS_REL: Path = Path("assets") / "gt-gpu"


@dataclass(frozen=True)
class LeakHit:
    """One potential model/vendor identity leak discovered inside a packaged build.

    Attributes:
        contender: source contender key ("kimi" or "opus")
        rel_path: file path relative to the build root
        match: matched identifying token
        snippet: short surrounding context for quick manual triage
    """

    contender: str
    rel_path: str
    match: str
    snippet: str


def scrub_html_title(html: str) -> str:
    """Replaces any identifying model/vendor token inside `<title>...</title>` with neutral text.

    Args:
        html: raw `index.html` contents

    Returns:
        sanitized HTML whose title never reveals a contender or vendor name
    """

    def _replace(match: re.Match[str]) -> str:
        """Neutralizes the `<title>` inner text only when it contains a leak token."""
        inner = match.group(2)
        if LEAK_PATTERN.search(inner):
            return f"{match.group(1)}Grand Theft GPU{match.group(3)}"
        return match.group(0)

    return re.sub(
        r"(<title\b[^>]*>)(.*?)(</title>)",
        _replace,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def scan_build_for_leaks(build_dir: Path, contender: str, max_hits: int = 25) -> list[LeakHit]:
    """Scans text assets in a packaged build for contender or vendor identifiers.

    Args:
        build_dir: packaged opaque build folder
        contender: source contender name (for reporting only)
        max_hits: cap on reported hits per build to keep CLI output readable

    Returns:
        list of `LeakHit` instances found in every non-media file, plus any `.map` file
    """
    hits: list[LeakHit] = []
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() in SKIP_SCAN_SUFFIXES:
            continue
        rel = path.relative_to(build_dir).as_posix()
        # Source maps carry original source and comments; players must never get them.
        if path.suffix.lower() == ".map":
            hits.append(LeakHit(contender, rel, ".map", "source map shipped in build"))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # Blank out allowlisted phrases before matching. Spaces keep every offset in place,
        # so the reported snippet can still be quoted from the original text.
        scanned = text
        for phrase in LEAK_ALLOWLIST:
            scanned = re.sub(
                re.escape(phrase),
                lambda m: " " * len(m.group(0)),
                scanned,
                flags=re.IGNORECASE,
            )

        for m in LEAK_PATTERN.finditer(scanned):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            snippet = text[start:end].replace("\n", " ").strip()
            hits.append(
                LeakHit(contender=contender, rel_path=rel, match=m.group(0), snippet=snippet)
            )
            if len(hits) >= max_hits:
                return hits
    return hits


# Vite's content-hashed bundle names (`index-CEyXDvVM.js`): stable per build and identical
# for every visitor, so one shared screenshot of DevTools would de-blind everyone.
_HASHED_BUNDLE_RE: re.Pattern[str] = re.compile(
    r"^(?P<stem>.+)-[A-Za-z0-9_-]{8}\.(?P<ext>js|mjs|css)$"
)

# Text files whose contents may reference bundle names and so get the renames applied.
_REFERENCE_SUFFIXES: frozenset[str] = frozenset({".html", ".js", ".mjs", ".css"})


def neutralize_bundle_names(build_dir: Path) -> dict[str, str]:
    """Strips Vite content hashes from `assets/` bundle names so both builds look alike.

    Renames `index-<hash>.js` to `index.js` (and likewise for CSS and code-split chunks)
    and rewrites every reference in the build's HTML, JS and CSS. A name is left alone
    when stripping its hash would collide with another file.

    Args:
        build_dir: packaged opaque build folder

    Returns:
        mapping of old file name to new file name for every rename applied
    """
    assets = build_dir / "assets"
    if not assets.is_dir():
        return {}
    taken = {p.name for p in assets.iterdir()}
    renames: dict[str, str] = {}
    for path in sorted(assets.iterdir()):
        match = _HASHED_BUNDLE_RE.match(path.name)
        if not path.is_file() or match is None:
            continue
        new_name = f"{match['stem']}.{match['ext']}"
        if new_name in taken:
            continue
        taken.add(new_name)
        renames[path.name] = new_name
    if not renames:
        return {}

    for path in build_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _REFERENCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        updated = text
        for old, new in renames.items():
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8", errors="surrogateescape")
    for old, new in renames.items():
        (assets / old).rename(assets / new)
    return renames


def _copy_dist_without_shared(src_dist: Path, dest_dir: Path) -> int:
    """Copies a Vite `dist/` tree while skipping the shared `assets/gt-gpu/` directory.

    Args:
        src_dist: contender's built `workspace/dist` folder
        dest_dir: destination opaque build directory (must not exist yet)

    Returns:
        total bytes copied into `dest_dir`
    """
    shared_abs = (src_dist / SHARED_ASSETS_REL).resolve()
    total_bytes = 0

    for src in sorted(src_dist.rglob("*")):
        if src.is_dir():
            continue
        # Skip the 650 MB shared asset pack; it streams from HF CDN or `_shared_assets`.
        if src.resolve().is_relative_to(shared_abs):
            continue
        rel = src.relative_to(src_dist)
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        total_bytes += dst.stat().st_size

    # Scrub any contender name that slipped into index.html <title>.
    index_path = dest_dir / "index.html"
    if index_path.exists():
        index_path.write_text(
            scrub_html_title(index_path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
    return total_bytes


def package_race(
    race_dir: Path,
    out_dir: Path,
    hf_assets_repo: str = DEFAULT_HF_ASSETS_REPO,
    hf_assets_revision: str = DEFAULT_HF_ASSETS_REVISION,
    link_local_assets: bool = False,
) -> tuple[ArenaManifest, list[LeakHit]]:
    """Packages both contenders from a race folder into opaque arena builds.

    Args:
        race_dir: path to `~/gta-race-runs/<race-id>` containing `kimi/` and `opus/`
        out_dir: output directory (usually `arena/builds`)
        hf_assets_repo: Hugging Face dataset repo hosting `assets/gt-gpu/`
        hf_assets_revision: pinned git commit SHA on `hf_assets_repo`
        link_local_assets: if True, symlink `out_dir/_shared_assets` to the local
            `assets/gt-gpu/` folder for offline local playtesting

    Returns:
        tuple of `(manifest, leak_hits)`

    Raises:
        FileNotFoundError: if either contender's `workspace/dist/index.html` is missing
    """
    sources: dict[str, Path] = {}
    for contender in CONTENDER_LABELS:
        dist = race_dir / contender / "workspace" / "dist"
        if not (dist / "index.html").exists():
            raise FileNotFoundError(f"missing built game: {dist / 'index.html'}")
        sources[contender] = dist

    # Rebuild out_dir cleanly so stale opaque builds from previous races never linger.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    builds_meta: dict[str, BuildMeta] = {}
    all_leaks: list[LeakHit] = []

    for contender, dist in sources.items():
        # Random opaque ID ensures directory listings and URLs never hint at model names.
        opaque_id = f"b-{secrets.token_hex(4)}"
        dest = out_dir / opaque_id
        copied_bytes = _copy_dist_without_shared(dist, dest)
        neutralize_bundle_names(dest)
        all_leaks.extend(scan_build_for_leaks(dest, contender))
        builds_meta[opaque_id] = {
            "contender": contender,
            "label": CONTENDER_LABELS[contender],
            "size_mb": round(copied_bytes / (1024 * 1024), 2),
        }

    # Optional local symlink lets `uvicorn app:app` serve shared assets with zero network calls.
    if link_local_assets:
        shared_src = sources["kimi"] / SHARED_ASSETS_REL
        if shared_src.exists():
            (out_dir / "_shared_assets").symlink_to(shared_src.resolve())

    manifest: ArenaManifest = {
        "race_id": race_dir.name,
        "hf_assets_repo": hf_assets_repo,
        "hf_assets_revision": hf_assets_revision,
        "builds": builds_meta,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, all_leaks


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser for `arena/prepare.py`."""
    parser = argparse.ArgumentParser(
        description="Package kimi + opus dist/ builds into blind opaque folders for the HF Space."
    )
    parser.add_argument(
        "--race-id",
        required=True,
        help="Race folder name under --runs-root (e.g. v15-full-100usd-001)",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=DEFAULT_RUNS_ROOT,
        help=f"Root directory holding race outputs (default: {DEFAULT_RUNS_ROOT})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "builds",
        help="Destination folder for opaque builds and manifest.json",
    )
    parser.add_argument(
        "--link-local-assets",
        action="store_true",
        help="Symlink local assets/gt-gpu/ into _shared_assets for offline local testing",
    )
    return parser


def main() -> None:
    """CLI entry point: packages both contenders and reports sizes and identity leaks."""
    args = build_parser().parse_args()
    race_dir = args.runs_root / args.race_id
    manifest, leaks = package_race(
        race_dir=race_dir,
        out_dir=args.out_dir,
        link_local_assets=args.link_local_assets,
    )

    print(f"Packaged race '{manifest['race_id']}' into {args.out_dir}")
    for build_id, info in manifest["builds"].items():
        print(f"  {build_id}: {info['label']} ({info['size_mb']} MB without shared assets)")

    if leaks:
        print(f"\nWARNING: {len(leaks)} possible identity leak(s) found — inspect before upload:")
        for hit in leaks:
            print(f"  [{hit.contender}] {hit.rel_path}: {hit.match!r} -> ...{hit.snippet}...")
        sys.exit(2)
    print("\nIdentity scan clean: zero contender/vendor tokens found.")


if __name__ == "__main__":
    main()
