#!/usr/bin/env python3
"""Check static extension JavaScript files are referenced.

Runtime UI features in this project are usually delivered by ``static/*_extension.js``
files injected through ``runtime_*.py`` middleware. A static extension that is not
referenced anywhere is dead code and can mislead future maintenance.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
SEARCH_GLOBS = [
    "*.py",
    "static/*.html",
    "static/*.js",
    "checks/*.py",
    "scripts/*.py",
]
SELF = Path(__file__).name
ALLOW_UNREFERENCED = set()


def _candidate_extensions() -> list[Path]:
    candidates = []
    for path in STATIC_DIR.glob("*extension*.js"):
        if path.name.endswith(".js"):
            candidates.append(path)
    return sorted(candidates)


def _search_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SEARCH_GLOBS:
        files.extend(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(set(files))


def _is_referenced(filename: str, search_files: list[Path]) -> bool:
    for path in search_files:
        if path.name == SELF:
            continue
        if path.name == filename:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if filename in content:
            return True
    return False


def main() -> int:
    search_files = _search_files()
    unreferenced = []
    for path in _candidate_extensions():
        if path.name in ALLOW_UNREFERENCED:
            continue
        if not _is_referenced(path.name, search_files):
            unreferenced.append(path.relative_to(ROOT).as_posix())
    if unreferenced:
        print("FAIL unreferenced static extension files:")
        for item in unreferenced:
            print(f"  - {item}")
        return 1
    print(f"OK static extension references checked ({len(_candidate_extensions())} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
