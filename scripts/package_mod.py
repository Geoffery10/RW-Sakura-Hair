#!/usr/bin/env python3
"""Build a clean, publishable copy of the mod.

Writes two things into dist/:
  dist/<ModFolderName>/                       staging folder for a Workshop upload
  dist/<ModFolderName>-<version>.zip          archive for a GitHub release

PSDs, .git, CI files and scripts never ship. On this repo the PSD folder is the
bulk of the size, so excluding it matters for Workshop upload time.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

# Folder names RimWorld reads, plus anything matching a version folder (1.6, 1.7).
INCLUDE_DIRS = {
    "About", "Assemblies", "AssetBundles", "Common", "Defs", "Languages",
    "Materials", "Patches", "Sounds", "Strings", "Textures",
}
INCLUDE_FILES = {"LoadFolders.xml"}
EXCLUDE_NAMES = {".git", ".github", "scripts", "dist", "PSD", "Source", ".vs", "bin", "obj", "__pycache__"}
VERSION_DIR = __import__("re").compile(r"^\d+\.\d+$")


def mod_version(mod_root: Path) -> str:
    manifest = mod_root / "About" / "Manifest.xml"
    if manifest.is_file():
        import xml.etree.ElementTree as ET

        try:
            node = ET.parse(str(manifest)).getroot().find("version")
            text = (node.text or "").strip() if node is not None else ""
            if text:
                return text
        except ET.ParseError:
            pass
    return "unversioned"


def wanted_dirs(mod_root: Path) -> list[Path]:
    out = []
    for child in sorted(mod_root.iterdir()):
        if not child.is_dir() or child.name in EXCLUDE_NAMES:
            continue
        if child.name in INCLUDE_DIRS or VERSION_DIR.match(child.name):
            out.append(child)
    return out


def build(mod_root: Path, folder_name: str, out_dir: Path) -> tuple[Path, Path]:
    staging = out_dir / folder_name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    copied = 0
    for directory in wanted_dirs(mod_root):
        shutil.copytree(directory, staging / directory.name, ignore=shutil.ignore_patterns(*EXCLUDE_NAMES))
        copied += sum(1 for _ in (staging / directory.name).rglob("*") if _.is_file())
    for filename in sorted(INCLUDE_FILES):
        source = mod_root / filename
        if source.is_file():
            shutil.copy2(source, staging / filename)
            copied += 1

    if not (staging / "About" / "About.xml").is_file():
        raise SystemExit("refusing to package: About/About.xml did not make it into the staging folder")

    archive = out_dir / f"{folder_name}-{mod_version(mod_root)}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zf.write(path, f"{folder_name}/{path.relative_to(staging)}")

    size_mb = archive.stat().st_size / 1_048_576
    print(f"staging : {staging} ({copied} files)")
    print(f"archive : {archive} ({size_mb:.2f} MB)")
    return staging, archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mod_root", nargs="?", default=".")
    parser.add_argument("--name", default="SakurasHair", help="destination folder name (no spaces)")
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()

    mod_root = Path(args.mod_root).resolve()
    if not mod_root.is_dir():
        print(f"not a directory: {mod_root}", file=sys.stderr)
        return 2
    if " " in args.name:
        print("--name must not contain spaces", file=sys.stderr)
        return 2

    build(mod_root, args.name, Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
