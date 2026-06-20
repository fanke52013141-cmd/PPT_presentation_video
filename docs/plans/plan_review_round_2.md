# Plan review round 2

Reviewer: Codex self-review

## Questions checked

1. Does TTS providerization break MiniMax?
   - It should not. Generic TTS delegates MiniMax to the existing `scripts/minimax_tts.py`.

2. Are provider-specific credentials isolated?
   - Yes. Settings now include provider, API key/SecretId, SecretKey, region, clone voice id, and provider extra JSON.

3. Is voice cloning actually represented?
   - Yes. Aliyun uses generated voice ids; Tencent uses `FastVoiceType`; Volcengine supports provider-specific extra fields.

## Adjustments

- Add `.env.example` placeholders for DashScope, Tencent, and Volcengine.
- Keep tests credential-free by checking command wiring and generated config behavior rather than calling paid APIs.
