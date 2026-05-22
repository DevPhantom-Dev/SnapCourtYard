"""Build SnapCourtYard PCM archive.

Output: dist/SnapCourtYard-<version>-pcm.zip
Install in KiCad: PCM > Install from File > pick the zip.
"""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
PCM_DIR = ROOT / "pcm"
DIST = ROOT / "dist"


def load_version():
    meta = json.loads((PCM_DIR / "metadata.json").read_text(encoding="utf-8"))
    return meta["versions"][0]["version"]


EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _excluded(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def build_zip(out_path: Path):
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


def main():
    if not PCM_DIR.is_dir():
        sys.exit(f"missing {PCM_DIR}")

    version = load_version()
    out = DIST / f"SnapCourtYard-{version}-pcm.zip"
    build_zip(out)

    digest = sha256(out)
    size = out.stat().st_size
    print(f"built: {out}")
    print(f"size:  {size} bytes")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
