from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as mask
import server


html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
mask_ui = (ROOT / "static" / "ai_mask_extension.js").read_text(encoding="utf-8")
css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

assert 'id="step2-script-full-prompt"' in html
assert 'id="step2-visual-full-prompt"' in html
assert "updateStep2FullPromptPreviews" in app
assert '<OutputExample>' in server.compose_step2_system_prompt("system", "example")
assert 'id="step6-btn-ai-prompt"' in html
assert 'id="step6-ai-system-prompt"' in html
assert 'id="step6-ai-output-example"' in html
assert 'id="step6-ai-full-prompt"' in html
assert "openStep6AnnotationPromptModal" in app
assert '<OutputExample>' in server.compose_narration_annotation_prompt("system", "example")
assert 'id="ai-mask-full-prompt"' in mask_ui
full_mask_prompt = mask._compose_ai_mask_full_prompt("method", "schema")
assert "method" in full_mask_prompt and "schema" in full_mask_prompt
assert "OUTPUT STRUCTURE / 输出结构" in full_mask_prompt
assert ".slide-thumbnail-card.step2-slide-thumb" in css
assert "height: 32px !important" in css

script_prompt = (ROOT / "templates" / "prompts" / "step2_script_system.md").read_text(encoding="utf-8")
visual_prompt = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
image_prompt = (ROOT / "templates" / "prompts" / "visual_draft.prompt.md").read_text(encoding="utf-8")
assert "输出字段只能是" in script_prompt
assert "完整演讲稿" in script_prompt
assert "按语义把整页 `narration` 切成" in visual_prompt
assert "视觉岛" in visual_prompt
assert "最小的 Mask/Reveal 原子" in visual_prompt
assert "多个独立卡片" in visual_prompt
assert "insufficient_visual_groups_for_independent_objects" in mask.DEFAULT_METHODOLOGY
assert "48-80 px" in image_prompt

sample_slides = [
    {
        "slide_id": "slide_001",
        "visual_groups": [
            {"id": "slide_001_el_001", "role": "content_body", "visual_type": "text", "display_text": "Alpha"}
        ],
    },
    {
        "slide_id": "slide_002",
        "visual_groups": [
            {"id": "slide_002_el_001", "role": "diagram", "visual_type": "illustration", "visual_anchor": "Beta"}
        ],
    },
]
batch_prompt = server.compose_step3_batch_copy_prompt("UNIQUE_GLOBAL_STYLE", sample_slides)
assert batch_prompt.count("UNIQUE_GLOBAL_STYLE") == 1
assert batch_prompt.count("Slide ID:") == 2
assert "slide_001" in batch_prompt and "slide_002" in batch_prompt
assert "step3BatchPrompt" in app

print("prompt and thumbnail checks passed")
