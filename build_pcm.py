"""Build SnapCourtYard PCM archive.

Usage:
    python build_pcm.py

Output: dist/SnapCourtYard-<version>-pcm.zip

Steps performed automatically:
  1. Copy plugin source from SnapCourtYard/ → pcm/plugins/
     (pcm/plugins/ is .gitignore'd; it is always regenerated here)
  2. Zip the entire pcm/ tree into dist/SnapCourtYard-<version>-pcm.zip
  3. Print path, size, and SHA-256 of the resulting archive

Install in KiCad: PCM → Install from File → pick the zip.
"""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT       = Path(__file__).parent
PCM_DIR    = ROOT / "pcm"
PLUGIN_SRC = ROOT / "SnapCourtYard"   # source of truth
PLUGIN_DST = PCM_DIR / "plugins"      # generated; not in git
DIST       = ROOT / "dist"

EXCLUDE_DIRS     = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def load_version() -> str:
    meta = json.loads((PCM_DIR / "metadata.json").read_text(encoding="utf-8"))
    return meta["versions"][0]["version"]


def _excluded(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def sync_plugins() -> None:
    """Copy SnapCourtYard/ → pcm/plugins/ (clean every time)."""
    if PLUGIN_DST.exists():
        shutil.rmtree(PLUGIN_DST)
    PLUGIN_DST.mkdir(parents=True)

    for src_path in sorted(PLUGIN_SRC.rglob("*")):
        if src_path.is_file() and not _excluded(src_path):
            rel      = src_path.relative_to(PLUGIN_SRC)
            dst_path = PLUGIN_DST / rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

    print(f"synced:  {PLUGIN_SRC.name}/ → {PLUGIN_DST.relative_to(ROOT)}/")


def build_zip(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PCM_DIR.rglob("*")):
            if path.is_file() and not _excluded(path):
                arc = path.relative_to(PCM_DIR).as_posix()
                zf.write(path, arc)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not PCM_DIR.is_dir():
        sys.exit(f"ERROR: missing {PCM_DIR}")
    if not PLUGIN_SRC.is_dir():
        sys.exit(f"ERROR: missing {PLUGIN_SRC}")

    version = load_version()
    out     = DIST / f"SnapCourtYard-{version}-pcm.zip"

    sync_plugins()
    build_zip(out)

    digest = sha256(out)
    size   = out.stat().st_size
    print(f"built:   {out}")
    print(f"size:    {size:,} bytes")
    print(f"sha256:  {digest}")


if __name__ == "__main__":
    main()
