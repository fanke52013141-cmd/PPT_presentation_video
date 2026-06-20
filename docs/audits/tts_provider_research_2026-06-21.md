# TTS provider research - 2026-06-21

This research was checked against official provider documentation where available.

## Alibaba Cloud Model Studio / CosyVoice

Sources:

- https://www.alibabacloud.com/help/en/model-studio/text-to-speech
- https://www.alibabacloud.com/help/en/model-studio/cosyvoice-clone-design-api
- https://www.alibabacloud.com/help/en/model-studio/voice-cloning-user-guide

Findings:

- CosyVoice supports real-time speech synthesis and voice customization.
- Voice cloning/design creates a custom voice id, which is then used as the voice for synthesis.
- This branch maps Aliyun to provider `aliyun_cosyvoice`.
- Expected credential: `DASHSCOPE_API_KEY`.
- Expected clone usage: fill `Clone Voice ID` with the generated voice id.

## Tencent Cloud TTS

Sources:

- https://www.tencentcloud.com/document/product/1154/48916
- https://www.tencentcloud.com/document/product/1154

Findings:

- Tencent Cloud TextToVoice converts text to speech through the `TextToVoice` action.
- Tencent auth uses SecretId/SecretKey with TC3 signing.
- `FastVoiceType` is the relevant parameter for instant/custom voice use.
- This branch maps Tencent to provider `tencent_tts`.
- Expected credential fields: `API Key / SecretId`, `SecretKey`, and optional `Region`.
- Expected clone usage: fill `Clone Voice ID`; backend passes it as `FastVoiceType`.

## Volcengine / Doubao / Seed Speech

Sources:

- https://www.volcengine.com/docs/6561/1257584

Findings:

- Volcengine HTTP non-streaming TTS supports `seed-tts-1.1` and model/request/audio parameters.
- The docs note cloned/replica scenarios have higher prompt-audio quality requirements.
- This branch maps Doubao/Volcengine to provider `volcengine_seed`.
- Expected credential: `VOLCENGINE_TTS_TOKEN`.
- Expected provider extra examples: `appid`, `cluster`, and optional `resource_id`.

## Implementation decision

The code now uses a provider-neutral wrapper:

- `scripts/generic_tts.py`
- Stable outputs remain compatible with the current video pipeline.
- Provider-specific details are contained in the wrapper and settings panel rather than scattered across `server.py`.
