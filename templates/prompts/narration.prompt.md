# Narration Annotation Prompt Contract

<PromptVersion>narration_annotation_v2_minimal</PromptVersion>

## Purpose / 目的

在用户已确认、并已绑定画面 Reveal 单元的中文旁白中加入少量 MiniMax TTS 标记。只优化朗读节奏，不重新生成、扩写或改写旁白。

## Inputs / 输入

每次只提交完成当前决策所需的字段：

```json
{
  "slides": [
    {
      "slide_id": "slide_001",
      "beats": [
        {"id": "beat_001", "source_text": "已确认的原始旁白"}
      ]
    }
  ]
}
```

不重复发送文章、标题、视觉描述、group ID、当前 TTS 文本或动画参数；这些字段不会改变停顿与轻量语气标注的决定。

## Output / 输出

只输出合法 JSON。保留输入顺序；每个 beat 只返回输入中的 `id` 和加入少量合法标记后的 `tts_text`。

去除 `<#x#>` 和允许的语气标签后，`tts_text` 必须与对应 `source_text` 完全一致。短句允许不加标记；停顿和语气标签不得位于段首、段尾或连续出现。

程序会再次校验文字一致性、标签合法性和 ID 来源；失败时回退到原始旁白，不接受模型改写。
