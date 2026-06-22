"""User-level runtime hooks for PPT Visualization Studio.

Python's site module imports ``usercustomize`` after ``sitecustomize`` when it is
available on ``sys.path``. Keep small optional bridges here to avoid rewriting the
large runtime hotfix file for every isolated hook.
"""

from __future__ import annotations

try:
    import runtime_settings_mask  # noqa: F401
except Exception:
    # Optional hardening must never prevent the local app from starting.
    pass
