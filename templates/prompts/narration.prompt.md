# Narration Prompt

## Purpose / 目的

根据当前 Slide 已实际存在的视觉组生成可直接用于 TTS 的中文旁白，使朗读顺序与 Reveal 顺序一致；不新增画面中不存在的事实或对象。

## Inputs / 输入

- 当前 Slide 在 `visual_contract.json` 中的 visual groups、内容摘要与 narration cues。
- 当前 Slide 在 `reveal_manifest.json` 中实际保留的可见组及顺序。
- 只处理当前 Slide，不复用其他页面的旁白。

## Output / 输出

- 只输出当前页最终旁白纯文本，不要 JSON、Markdown、标题、解释或舞台说明。
- 输出必须可直接交给 MiniMax TTS。

## Visual Binding Requirement

Write narration from the current slide's actual visible groups. Use the group
summaries and narration cues from `visual_contract.json` and
`reveal_manifest.json`.
Do not reuse narration from another slide.

The narration order should match the intended visual reveal:

1. title/subtitle context
2. main explanation group
3. diagram/example group
4. closing summary group

If a visible group has no matching sentence, add one. If a sentence describes
content not visible on the slide, remove or rewrite it.

请把 slide 的核心信息改写成适合 MiniMax TTS 的旁白。

要求：

- 中文短句。
- 语气清楚、自然、可信。
- 每页 90 到 180 个中文字符。
- 术语后马上解释。
- 可以使用 `<#0.4#>` 这类停顿标记，但不要连续使用。
- 不要写舞台说明，不要写括号里的情绪说明，除非用户明确要求。

