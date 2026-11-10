# Changelog

Newest first. Headings name the RimWorld versions the mod supports as of that
release, which is the thing Workshop users care about.

## 1.7 - 2026-11-09

- Support RimWorld 1.7 (Waylith engine). No content changes were required: the
  mod is pure XML, so the existing hair defs load unchanged.
- Added `1.7/Defs/HairDefs/Hair.xml` and `<li>1.7</li>` to `supportedVersions`.
- New preview image.
- Added `scripts/validate_mod.py` and `scripts/package_mod.py` plus CI workflows
  for validation, packaging and tagged releases.
- Workshop uploads are now built from `dist/`, which excludes `PSD/` and `.git`
  so the item no longer carries source art. The PSDs stay in the repository.

## 1.6 - 2025-07-13

- Support RimWorld 1.6.

## 1.5 - 2024-09-09

- Support RimWorld 1.5.
- New mod icon.

## 2023-09-28

- Reduced the forehead on the hair sprites.

## 2023-09-27

- Adjusted hair width.

## 2023-08-09

- Initial commit: hair def for RimWorld 1.0 through 1.4, textures, preview,
  Steam Workshop item 3007906745.
