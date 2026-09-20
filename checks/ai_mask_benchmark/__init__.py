"""AI Mask benchmark isolated runner (handoff package W0).

Never touches the user's real ``data/`` or ``runs/`` directories: the DB and
runs roots are re-pointed at a temporary directory before any application
import. See ``runner.py`` for the entry point and ``freeze_baseline.py`` for
the frozen comparison baseline.
"""
