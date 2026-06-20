# Visual-Narration Binding

- Narration must be written after the slide's visible groups are known.
- Every major visible group should be introduced, explained, or extended
  by narration.
- Do not reuse narration, subtitles, or audio from another slide or earlier run.
- The broad narration order should match visual reveal order: title/subtitle,
  main content groups, diagram/example, summary.
- `visual_contract.json` and `reveal_manifest.json` should keep stable group
  ids and visible text for narration binding.
- If the current narration cannot be matched to the visible group summaries,
  rewrite narration before TTS.

# 旁白规则

## 句式

- 每句尽量短，适合 TTS 自然朗读。
- 一句话只讲一个信息点。
- 少用嵌套从句。
- 术语后面立刻补一句解释。

## 节奏

- 开场 15 秒内提出问题。
- 每 20 到 30 秒给一个明确小结。
- 每页旁白建议 90 到 180 个中文字符，但不要为了凑字数增加空话。
- 需要停顿时可以使用 `<#0.25#>`、`<#0.4#>`、`<#0.6#>`、`<#0.8#>`。
- 停顿只放在两个可发音文本之间。
- 不在整段开头或结尾加停顿。
- 不在一句话开头或结尾加停顿。
- 不连续使用多个停顿标记。
- 不滥用长停顿，默认不超过 1 秒。

## MiniMax 语气标签

本项目默认只允许少数自然讲解标签：

- `(breath)`：自然换气，只用于长解释中间。
- `(emm)`：轻微思考，只在引出类比或口语化转折时使用。
- `(chuckle)`：轻笑，只在轻松例子或温和纠错时使用。
- `(laughs)`：笑声，极少使用，默认不用。
- `(sighs)`：轻叹，只在讲常见困惑、踩坑或误区时使用。

规则：

- 每页默认 0 到 2 个语气标签。
- 不要求每页都有语气标签。
- 不在文本开头或结尾放语气标签。
- 语气标签不能替代真实内容。
- 其它强表演或不适合科普讲解的拟声标签默认不使用。

## Emotion

- 默认使用 `calm`。
- 可以少量使用 `happy` 或 `surprised`。
- 默认不使用强烈负面情绪。
- 不使用低语风格，避免听不清楚。

## 风格

- 像一个清楚的科普讲解者，不像论文摘要。
- 不夸张，不制造恐慌。
- 可以用类比，但类比后要回到准确表达。
- 语气自然，但不过度表演。

## 禁止

- “众所周知”这类空泛开头。
- 未核实的绝对化判断。
- 大段英文术语堆叠。
- 超过 40 字的长句。
- 停顿和语气标签出现在字幕中。
