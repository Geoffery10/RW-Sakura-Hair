#!/usr/bin/env python3
"""Validate a RimWorld mod without launching the game.

Exits 0 when there are no errors, 1 otherwise. Warnings never fail the run.
Pure stdlib: no pip install, no game files, runs on any CI runner.

Usage:
    python3 scripts/validate_mod.py .
    python3 scripts/validate_mod.py . --strict     # warnings become errors
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ERRORS: list[str] = []
WARNINGS: list[str] = []
NOTES: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def note(msg: str) -> None:
    NOTES.append(msg)


VERSION_RE = re.compile(r"^\d+\.\d+$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
DEFNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Folder names RimWorld resolves case-sensitively on Linux/macOS.
CASE_SENSITIVE = [
    "About", "Assemblies", "AssetBundles", "Common", "Defs", "Languages",
    "Materials", "Patches", "Sounds", "Strings", "Textures",
]

GENDERS = {"Male", "Female", "Any", "None"}
HAIR_DIRECTIONS = ("south", "north", "east")  # west is mirrored from east
PREVIEW_MAX_BYTES = 1_000_000  # Steam rejects Preview.png over 1 MB
PREVIEW_SIZES = {(640, 360), (1280, 720)}
ICON_SIZES = {(32, 32), (64, 64)}


def ver(v: str) -> tuple[int, int]:
    major, minor = v.split(".")
    return int(major), int(minor)


def png_size(path: Path) -> tuple[int, int] | None:
    """Read width/height straight out of the PNG IHDR chunk (no Pillow)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(26)
    except OSError:
        return None
    if len(head) < 26 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def load_xml(path: Path) -> ET.Element | None:
    try:
        return ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        err(f"{path}: XML is not well-formed: {exc}")
        return None
    except OSError as exc:
        err(f"{path}: cannot read: {exc}")
        return None


def check_all_xml(root: Path, mod_root: Path) -> None:
    for path in sorted(mod_root.rglob("*.xml")):
        if any(part in {".git", "scripts", "dist"} for part in path.parts):
            continue
        load_xml(path)  # records parse errors itself


def check_case_sensitivity(mod_root: Path) -> None:
    for child in mod_root.iterdir():
        if not child.is_dir():
            continue
        if child.name.lower() in {d.lower() for d in CASE_SENSITIVE} and child.name not in CASE_SENSITIVE:
            err(f"folder '{child.name}/' must be exactly '{child.name.title()}/' (case matters on Linux)")


def check_about(mod_root: Path) -> dict:
    about_path = mod_root / "About" / "About.xml"
    if not about_path.is_file():
        err("About/About.xml is missing (required for the game to see the mod)")
        return {}

    root = load_xml(about_path)
    if root is None:
        return {}

    info: dict = {}
    for field in ("name", "author", "packageId", "description"):
        node = root.find(field)
        text = (node.text or "").strip() if node is not None else ""
        info[field] = text
        if not text:
            err(f"About.xml: <{field}> is empty or missing")

    pkg = info.get("packageId", "")
    if pkg:
        if not PACKAGE_RE.match(pkg):
            err(f"About.xml: packageId '{pkg}' may only contain letters, digits, '.' and '_' (no spaces)")
        if "." not in pkg:
            warn(f"About.xml: packageId '{pkg}' has no dot; Ludeon's convention is Reverse.Domain.ModName")

    versions: list[str] = []
    sv = root.find("supportedVersions")
    if sv is None:
        err("About.xml: <supportedVersions> is missing")
    else:
        for li in sv.findall("li"):
            raw = (li.text or "").strip()
            if not raw:
                warn("About.xml: empty <li> inside supportedVersions")
            elif not VERSION_RE.match(raw):
                err(f"About.xml: supportedVersions entry '{raw}' is not in X.Y form")
            else:
                versions.append(raw)

    if len(versions) != len(set(versions)):
        err("About.xml: duplicate entries in supportedVersions")
    if versions and versions != sorted(versions, key=ver):
        warn("About.xml: supportedVersions is not in ascending order")
    info["versions"] = versions

    desc = info.get("description", "")
    if desc and len(desc) < 20:
        warn("About.xml: description is very short; Workshop shoppers see this text")

    return info


def check_assets(mod_root: Path) -> None:
    preview = mod_root / "About" / "Preview.png"
    if not preview.is_file():
        err("About/Preview.png is missing (required; the Workshop uses it as the item preview)")
    else:
        size = preview.stat().st_size
        if size > PREVIEW_MAX_BYTES:
            err(f"About/Preview.png is {size} bytes; Steam rejects preview files over {PREVIEW_MAX_BYTES}")
        dims = png_size(preview)
        if dims is None:
            err("About/Preview.png is not a valid PNG (RimWorld needs the .png extension and real PNG bytes)")
        elif dims not in PREVIEW_SIZES:
            warn(f"About/Preview.png is {dims[0]}x{dims[1]}; vanilla expects 640x360 or 1280x720")

    icon = mod_root / "About" / "ModIcon.png"
    if icon.is_file():
        dims = png_size(icon)
        if dims is None:
            err("About/ModIcon.png is not a valid PNG")
        elif dims not in ICON_SIZES:
            warn(f"About/ModIcon.png is {dims[0]}x{dims[1]}; expected 32x32 or 64x64")

    pfid = mod_root / "About" / "PublishedFileId.txt"
    if pfid.is_file():
        value = pfid.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not value.isdigit():
            err(f"About/PublishedFileId.txt contains '{value}', which is not a numeric Workshop id")
        else:
            note(f"Workshop item id {value}: only the owning Steam account can update it")
    else:
        note("No About/PublishedFileId.txt: the first upload will create a new Workshop item")


def check_manifest(mod_root: Path, about: dict) -> None:
    manifest = mod_root / "About" / "Manifest.xml"
    if not manifest.is_file():
        return
    root = load_xml(manifest)
    if root is None:
        return
    node = root.find("version")
    version = (node.text or "").strip() if node is not None else ""
    note(f"About/Manifest.xml declares version {version or '(none)'}; that file is obsolete, About.xml is authoritative")


def version_folders(mod_root: Path) -> list[str]:
    return sorted(
        (c.name for c in mod_root.iterdir() if c.is_dir() and VERSION_RE.match(c.name)),
        key=ver,
    )


def load_sets(mod_root: Path, versions: list[str]) -> tuple[dict[str, list[Path]], bool]:
    """Map each supported game version to the folders the game actually loads.

    LoadFolders.xml wins when present. Otherwise RimWorld 1.1+ loads the highest
    versioned folder whose version is <= the running version, plus root folders.
    """
    folders = version_folders(mod_root)
    loadfolders = mod_root / "LoadFolders.xml"

    if loadfolders.is_file():
        root = load_xml(loadfolders)
        if root is not None:
            sets: dict[str, list[Path]] = {}
            for child in root:
                name = child.tag[1:] if child.tag.lower().startswith("v") else child.tag
                if not VERSION_RE.match(name):
                    continue
                dirs: list[Path] = []
                for li in child.findall("li"):
                    raw = (li.text or "").strip()
                    if raw in {"", "/"}:
                        dirs.append(mod_root)
                        continue
                    candidate = mod_root / raw
                    if candidate.is_dir():
                        dirs.append(candidate)
                    else:
                        err(f"LoadFolders.xml: declares folder '{raw}' under {child.tag} but it does not exist")
                sets[name] = dirs
            return sets, True
        return {}, True

    sets = {}
    for v in versions:
        candidates = [f for f in folders if ver(f) <= ver(v)]
        chosen = max(candidates, key=ver) if candidates else None
        dirs = [mod_root]
        if chosen:
            dirs.append(mod_root / chosen)
        sets[v] = dirs
    return sets, False


def resolve_load_folders(mod_root: Path, sets: dict[str, list[Path]], using_loadfolders: bool) -> None:
    if using_loadfolders:
        for v in sorted(sets, key=ver):
            names = ", ".join(p.name if p != mod_root else "/" for p in sets[v])
            note(f"game {v} -> LoadFolders.xml: {names}")
    else:
        for v in sorted(sets, key=ver):
            chosen = [p.name for p in sets[v] if p != mod_root]
            note(f"game {v} -> loads {', '.join(chosen) if chosen else '(root only)'}")

    folders = version_folders(mod_root)
    if not using_loadfolders:
        for f in folders:
            if f not in sets:
                warn(f"folder {f}/ exists but {f} is not in supportedVersions (dead weight)")


def resolve_set(s: list[Path]) -> dict[str, Path]:
    """Collapse a load set to relative-path -> winning file, later entries shadowing."""
    resolved: dict[str, Path] = {}
    for base in s:
        for path in sorted((base / "Defs").rglob("*.xml")) if (base / "Defs").is_dir() else []:
            resolved[str(path.relative_to(base))] = path
    return resolved


def check_defs(mod_root: Path, sets: dict[str, list[Path]]) -> None:
    textures = mod_root / "Textures"
    if not sets:
        sets = {"(all)": [mod_root] + [mod_root / f for f in version_folders(mod_root)]}

    checked_dirs: set[tuple[str, ...]] = set()
    for game_version, dirs in sorted(sets.items(), key=lambda kv: ver(kv[0])):
        signature = tuple(str(d) for d in dirs)
        # Defs are checked per distinct load set; duplicate sets share a result.
        if signature in checked_dirs:
            continue
        checked_dirs.add(signature)

        seen: dict[str, str] = {}
        for rel, path in resolve_set(dirs).items():
            root = load_xml(path)
            if root is None:
                continue
            where = f"[{game_version}] {path.relative_to(mod_root)}"
            for def_node in root:
                tag = def_node.tag
                defname = (def_node.findtext("defName") or "").strip()
                if not defname:
                    err(f"{where}: <{tag}> has no defName")
                    continue
                if not DEFNAME_RE.match(defname):
                    err(f"{where}: defName '{defname}' may only contain letters, digits and '_'")
                if defname in seen:
                    err(f"{where}: defName '{defname}' already defined in {seen[defname]} (same load set)")
                seen[defname] = where

                if tag != "HairDef":
                    continue

                if not (def_node.findtext("label") or "").strip():
                    err(f"{where}: HairDef '{defname}' has no <label>")

                gender = (def_node.findtext("styleGender") or def_node.findtext("hairGender") or "").strip()
                if not gender:
                    warn(f"{where}: HairDef '{defname}' has no styleGender")
                elif gender not in GENDERS:
                    err(f"{where}: styleGender '{gender}' is not one of {sorted(GENDERS)}")

                tex = (def_node.findtext("texPath") or "").strip()
                if not tex:
                    err(f"{where}: HairDef '{defname}' has no <texPath>")
                    continue
                for direction in HAIR_DIRECTIONS:
                    candidate = textures / f"{tex}_{direction}.png"
                    if not candidate.is_file():
                        err(f"{where}: texPath '{tex}' is missing {candidate.relative_to(mod_root)}")

                tags_node = def_node.find("styleTags")
                if tags_node is None:
                    tags_node = def_node.find("hairTags")
                if tags_node is None or not list(tags_node):
                    warn(f"{where}: HairDef '{defname}' has no styleTags")


def check_duplicate_content(mod_root: Path, folders: list[str]) -> None:
    """Byte-identical defs across version folders are maintenance debt."""
    defs_dir_files = []
    for f in folders:
        for path in sorted((mod_root / f / "Defs").rglob("*.xml")):
            defs_dir_files.append((f, path))
    if len(defs_dir_files) < 2:
        return
    by_hash: dict[bytes, list[str]] = {}
    for folder, path in defs_dir_files:
        by_hash.setdefault(path.read_bytes(), []).append(folder)
    for folders_with_same in by_hash.values():
        if len(folders_with_same) > 1:
            note(f"identical defs in {', '.join(sorted(folders_with_same, key=ver))} - consolidation candidate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mod_root", nargs="?", default=".", help="path to the mod repository root")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args()

    mod_root = Path(args.mod_root).resolve()
    if not mod_root.is_dir():
        print(f"not a directory: {mod_root}", file=sys.stderr)
        return 2

    check_all_xml(mod_root, mod_root)
    check_case_sensitivity(mod_root)
    about = check_about(mod_root)
    check_assets(mod_root)
    check_manifest(mod_root, about)
    versions = about.get("versions") or []
    sets, using_loadfolders = load_sets(mod_root, versions)
    resolve_load_folders(mod_root, sets, using_loadfolders)
    check_defs(mod_root, sets)
    check_duplicate_content(mod_root, version_folders(mod_root))

    if args.strict:
        ERRORS.extend(f"warning treated as error: {w}" for w in WARNINGS)
        WARNINGS.clear()

    for line in NOTES:
        print(f"  note  {line}")
    for line in WARNINGS:
        print(f"  WARN  {line}")
    for line in ERRORS:
        print(f"  FAIL  {line}")

    print()
    print(f"{len(ERRORS)} error(s), {len(WARNINGS)} warning(s), {len(NOTES)} note(s)")
    if ERRORS:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
