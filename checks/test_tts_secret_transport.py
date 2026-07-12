from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


def test_tts_credentials_are_not_command_line_arguments() -> None:
    api_key = "audit-api-key"
    secret_key = "audit-secret-key"
    command = server.provider_tts_command(
        provider="minimax",
        text_file="input.txt",
        out_audio="voice.mp3",
        out_meta="meta.json",
        out_srt="voice.srt",
        out_timeline="timeline.json",
        slide_id="slide_001",
        endpoint="https://example.invalid",
        region="",
        model="model",
        voice_id="voice",
        clone_voice_id="",
        provider_extra="",
        speed="1",
        volume="1",
        pitch="0",
    )
    assert "--api-key" not in command
    assert "--secret-key" not in command
    assert api_key not in command
    assert secret_key not in command

    environment = server.provider_tts_environment(api_key, secret_key)
    assert environment[server.TTS_API_KEY_ENV] == api_key
    assert environment[server.TTS_SECRET_KEY_ENV] == secret_key


def test_minimax_adapter_does_not_forward_key_on_command_line() -> None:
    source = (ROOT / "scripts" / "generic_tts.py").read_text(encoding="utf-8")
    assert 'cmd.extend(["--api-key", args.api_key])' not in source
    assert 'child_env["MINIMAX_API_KEY"]' in source


if __name__ == "__main__":
    test_tts_credentials_are_not_command_line_arguments()
    test_minimax_adapter_does_not_forward_key_on_command_line()
    print("TTS secret transport checks passed")
