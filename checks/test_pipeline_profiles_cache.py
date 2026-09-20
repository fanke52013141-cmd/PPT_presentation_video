from __future__ import annotations

from pathlib import Path

import scripts.pipeline_profiles as profiles


def test_profile_cache_reuses_unchanged_file_and_returns_isolated_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("storyboard:\n  enabled: true\n", encoding="utf-8")
    profiles._PROFILE_CACHE.clear()

    calls = 0
    original_load = profiles.yaml.safe_load

    def counted_load(value: object) -> object:
        nonlocal calls
        calls += 1
        return original_load(value)

    monkeypatch.setattr(profiles.yaml, "safe_load", counted_load)
    first = profiles.read_pipeline_profile(profile_path)
    first["storyboard"]["enabled"] = False
    second = profiles.read_pipeline_profile(profile_path)

    assert calls == 1
    assert second == {"storyboard": {"enabled": True}}


def test_profile_cache_invalidates_when_file_changes(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profiles._PROFILE_CACHE.clear()
    profile_path.write_text("version: one\n", encoding="utf-8")
    assert profiles.read_pipeline_profile(profile_path) == {"version": "one"}

    profile_path.write_text("version: two\nupdated: true\n", encoding="utf-8")
    assert profiles.read_pipeline_profile(profile_path) == {
        "version": "two",
        "updated": True,
    }
