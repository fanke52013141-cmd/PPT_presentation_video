"""Motion preparation must preserve identity inputs and reject false success."""
from pathlib import Path
import subprocess

import pytest

from digital_human_motion import PortraitRuntime, motion_cache_key, prepare_portrait_base


def setup_inputs(tmp_path):
    photo = tmp_path / "teacher.png"
    video = tmp_path / "template.mp4"
    photo.write_bytes(b"portrait-b")
    video.write_bytes(b"motion-a")
    repository = tmp_path / "runtime"
    repository.mkdir()
    (repository / "inference.py").touch()
    python = repository / "python.exe"
    python.touch()
    return photo, video, PortraitRuntime(repository, python, "model-revision-a")


def test_content_cache_and_corrupt_output_rebuild(tmp_path):
    photo, video, runtime = setup_inputs(tmp_path)
    calls = []

    def execute(argv, **kwargs):
        calls.append(argv)
        assert Path(argv[argv.index("-s") + 1]).read_bytes() == b"portrait-b"
        assert Path(argv[argv.index("-d") + 1]).read_bytes() == b"motion-a"
        assert kwargs["timeout"] == 3600
        (Path(argv[argv.index("-o") + 1]) / "portrait--driving.mp4").write_bytes(b"real-result")

    def validate(path):
        assert path.read_bytes() == b"real-result"

    def prepare():
        return prepare_portrait_base(photo, video, tmp_path / "cache", runtime,
                                     execute=execute, validate_video=validate)

    base = prepare()
    assert prepare() == base
    assert len(calls) == 1
    base.write_bytes(b"corrupt")
    assert prepare().read_bytes() == b"real-result"
    assert len(calls) == 2
    previous = motion_cache_key(photo, video, runtime.revision)
    photo.write_bytes(b"different-identity")
    assert previous != motion_cache_key(photo, video, runtime.revision)
    assert previous != motion_cache_key(photo, video, "different-model")


def test_failed_transfer_is_not_published_or_replaced_by_driver(tmp_path):
    photo, video, runtime = setup_inputs(tmp_path)

    def execute(*args, **kwargs):
        raise subprocess.TimeoutExpired("inference", 3600)

    with pytest.raises(subprocess.TimeoutExpired):
        prepare_portrait_base(photo, video, tmp_path / "cache", runtime,
                              execute=execute, validate_video=lambda p: None)
    assert not list((tmp_path / "cache").rglob("complete.json"))
    assert not list((tmp_path / "cache").rglob("base.mp4"))


def test_disallows_untrusted_serialized_driving_template(tmp_path):
    photo, video, runtime = setup_inputs(tmp_path)
    serialized = video.with_suffix(".pkl")
    serialized.write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="序列化"):
        prepare_portrait_base(photo, serialized, tmp_path / "cache", runtime,
                              execute=lambda *a, **k: None, validate_video=lambda p: None)
