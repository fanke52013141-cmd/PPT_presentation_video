# Narration Prompt

## Visual Binding Requirement

Write narration from the current slide's actual macro layers. Use the layer
summaries and narration cues from `layer_manifest.json` / `scene.layers[]`.
Do not reuse narration from another slide.

The narration order should match the intended visual reveal:

1. title/subtitle context
2. main explanation group
3. diagram/example group
4. closing summary group

If a visible layer has no matching sentence, add one. If a sentence describes
content not visible on the slide, remove or rewrite it.

请把 slide 的核心信息改写成适合 MiniMax TTS 的旁白。

要求：

- 中文短句。
- 语气清楚、自然、可信。
- 每页 90 到 180 个中文字符。
- 术语后马上解释。
- 可以使用 `<#0.4#>` 这类停顿标记，但不要连续使用。
- 不要写舞台说明，不要写括号里的情绪说明，除非用户明确要求。

