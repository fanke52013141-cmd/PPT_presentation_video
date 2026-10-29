from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

import model_voice_reference_service as service


def connection():
    return {"kind": "tts", "revision": {"provider": "comfyui_tts", "public_config": {"voice_setting": "retained"}}}


def test_metadata_failure_restores_previous_audio_and_cleans_pending(monkeypatch, tmp_path):
    old = tmp_path / "voice.mp3"
    old.write_bytes(b"original")
    monkeypatch.setattr(service.connections, "get_model_connection", lambda _: connection())
    def reject(*_):
        raise OSError("controlled metadata failure")
    monkeypatch.setattr(service.connections, "update_model_connection", reject)
    with pytest.raises(OSError):
        service.publish_reference_audio("voice", "new.wav", b"replacement", tmp_path, probe=lambda _: 1)
    assert old.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["voice.mp3"]


@pytest.mark.parametrize("duration", [None, 0, -1, float("nan"), float("inf"), 31])
def test_probe_failure_keeps_prior_file_and_does_not_change_metadata(monkeypatch, tmp_path, duration):
    old = tmp_path / "voice.wav"
    old.write_bytes(b"original")
    monkeypatch.setattr(service.connections, "get_model_connection", lambda _: connection())
    monkeypatch.setattr(service.connections, "update_model_connection", lambda *_: pytest.fail("invalid audio published"))
    with pytest.raises(ValueError):
        service.publish_reference_audio("voice", "new.wav", b"invalid", tmp_path, probe=lambda _: duration)
    assert list(tmp_path.iterdir()) == [old] and old.read_bytes() == b"original"


def test_concurrent_uploads_have_unique_staging_and_serialized_publication(monkeypatch, tmp_path):
    monkeypatch.setattr(service.connections, "get_model_connection", lambda _: connection())
    barrier = threading.Barrier(2)
    paths, updates = [], []
    def probe(path):
        paths.append(path)
        barrier.wait(timeout=5)
        assert path.read_bytes() in (b"one", b"two")
        return 1
    def update(cid, payload):
        value = payload.public_config
        assert value["voice_setting"] == "retained"
        target = tmp_path / value["clone_voice_id"].rsplit("/", 1)[1]
        updates.append(target.read_bytes())
        return {"id": cid, "revision": {"public_config": value}}
    monkeypatch.setattr(service.connections, "update_model_connection", update)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.publish_reference_audio, "voice", "new.wav", value, tmp_path, probe=probe)
                   for value in (b"one", b"two")]
        for future in futures:
            assert future.result()["reference_audio"]["duration_sec"] == 1
    assert len(set(paths)) == 2
    assert set(updates) == {b"one", b"two"}
    assert (tmp_path / "voice.wav").read_bytes() == updates[-1]
    assert len(list(tmp_path.iterdir())) == 1
