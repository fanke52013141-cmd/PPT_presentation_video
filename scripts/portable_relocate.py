"""Portable-package relocation adapter (runs before every server start).

The portable package records its build-time root in ``data/.portable_root``.
When the whole folder is copied or moved to another location (another drive,
another computer), absolute paths stored inside the package still point at the
old root.  This script detects the change and transparently rewrites:

* ``data/**/*.json`` and ``data/**/*.yaml`` text registries (model
  connections, creation configs, style tokens, ...) -- plain-text replace of
  the old root in both slash directions, including the escaped ``\\\\``
  forms used inside JSON string values;
* ``settings`` values and ``projects.run_dir`` in ``data/projects.db``.

Idempotent and fast: when the recorded root equals the current root it exits
immediately without touching anything.  Failures are reported but never block
startup for more than the time of one pass.

This module is packaging infrastructure only: it must stay independent of
FastAPI, the database ORM, and the application module (plain sqlite3/json).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / "data" / ".portable_root"


def _variants(old_root: str) -> list[str]:
    fwd = old_root.replace("\\", "/")
    return [
        old_root,
        fwd,
        old_root.replace("\\", "\\\\"),
        fwd.replace("/", "\\/"),
    ]


def _rewrite_text_files(old_root: str) -> int:
    changed = 0
    cur = str(ROOT)
    cur_fwd = cur.replace("\\", "/")
    pairs = list(zip(
        _variants(old_root),
        [cur, cur_fwd, cur.replace("\\", "\\\\"), cur_fwd.replace("/", "\\/")],
    ))
    for pattern in ("*.json", "*.yaml"):
        for path in (ROOT / "data").rglob(pattern):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new_text = text
            for old_v, new_v in pairs:
                new_text = new_text.replace(old_v, new_v)
            if new_text != text:
                path.write_text(new_text, encoding="utf-8", newline="")
                changed += 1
                print(f"[relocate] rewrote {path.relative_to(ROOT)}")
    return changed


def _rewrite_database(old_root: str) -> int:
    db = ROOT / "data" / "projects.db"
    if not db.exists():
        return 0
    changed = 0
    cur_root = str(ROOT)
    pairs = list(zip(_variants(old_root), _variants(cur_root)))
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
        for key, value in rows:
            if not isinstance(value, str) or old_root not in value and old_root.replace("\\", "/") not in value:
                continue
            new_value = value
            for old_v, new_v in pairs:
                new_value = new_value.replace(old_v, new_v)
            if new_value != value:
                con.execute("UPDATE settings SET value = ? WHERE key = ?", (new_value, key))
                changed += 1
                print(f"[relocate] settings.{key} path updated")
        try:
            run_rows = con.execute("SELECT id, run_dir FROM projects").fetchall()
        except sqlite3.OperationalError:
            run_rows = []
        for project_id, run_dir in run_rows:
            if not isinstance(run_dir, str):
                continue
            new_dir = run_dir
            for old_v, new_v in pairs:
                new_dir = new_dir.replace(old_v, new_v)
            if new_dir != run_dir:
                con.execute("UPDATE projects SET run_dir = ? WHERE id = ?", (new_dir, project_id))
                changed += 1
        con.commit()
    finally:
        con.close()
    return changed


def main() -> int:
    if not MARKER.exists():
        # First run without a recorded root (e.g. dev checkout): nothing to
        # migrate from, just record the current location.
        MARKER.write_text(json.dumps({"root": str(ROOT)}), encoding="utf-8")
        return 0
    try:
        recorded = json.loads(MARKER.read_text(encoding="utf-8")).get("root")
    except (OSError, ValueError):
        recorded = None
    if not recorded:
        MARKER.write_text(json.dumps({"root": str(ROOT)}), encoding="utf-8")
        return 0

    import os

    if os.path.normcase(str(Path(recorded).resolve())) == os.path.normcase(str(ROOT)):
        return 0

    print(f"[relocate] package moved: {recorded} -> {ROOT}")
    total = _rewrite_text_files(recorded)
    total += _rewrite_database(recorded)
    MARKER.write_text(json.dumps({"root": str(ROOT)}), encoding="utf-8")
    print(f"[relocate] done: {total} field(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
