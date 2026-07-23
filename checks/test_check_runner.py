from __future__ import annotations

from scripts.run_checks import ROOT, standalone_python_checks


def test_full_check_runner_includes_script_style_checks() -> None:
    discovered = set(standalone_python_checks())

    assert ROOT / "checks" / "test_audio_confirmation.py" in discovered
    assert ROOT / "checks" / "test_video_speed.py" in discovered
    assert ROOT / "checks" / "test_video_routes.py" not in discovered
