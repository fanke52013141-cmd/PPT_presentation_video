from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as mask
import server
from scripts import write_visual_prompts


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
assert 'id="step3-btn-prompt-settings"' in html
assert 'id="step3-image-system-prompt"' in html
assert 'id="step3-image-input-preview"' in html
assert 'id="step3-image-full-prompt"' in html
assert 'data-prompt-help="step3-image"' in html
assert 'data-prompt-help="narration-annotation"' in html
assert "openStep6AnnotationPromptModal" in app
assert "openStep3PromptSettingsModal" in app
assert "PROMPT_IO_HELP" in app
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
step3_system_prompt = (ROOT / "templates" / "prompts" / "step3_image_system.md").read_text(encoding="utf-8")
assert "step2_script_v5_speech_driven" in script_prompt
assert "认知旅程" in script_prompt
assert "完整演讲稿" in script_prompt
assert "step2_visual_v6_atomic" in visual_prompt
assert "先按语义切分整页 `narration`" in visual_prompt
assert "视觉岛" in visual_prompt
assert "最小 Mask/Reveal 原子" in visual_prompt
assert "多个独立卡片" in visual_prompt
assert "不预设正文元素数量" in visual_prompt
assert "标点必须完整归入" in visual_prompt
assert "insufficient_visual_groups_for_independent_objects" in mask.DEFAULT_METHODOLOGY
assert "必要且最小" in image_prompt
assert "step3_image_v2_minimal_mask_ready" in step3_system_prompt
assert "`main_title` 和 `body_elements`" in step3_system_prompt
assert "完整文章、完整旁白" in step3_system_prompt
assert "32–64 px" in step3_system_prompt

sample_slides = [
    {
        "slide_id": "slide_001",
        "main_title": "First title",
        "visual_groups": [
            {"id": "slide_001_el_001", "role": "title", "visual_type": "text", "display_text": "First title"},
            {"id": "slide_001_el_002", "role": "content_body", "visual_type": "text", "display_text": "Alpha", "narration_function": "do not send"}
        ],
        "narration": "must not enter image input",
        "core_message": "must not enter image input",
    },
    {
        "slide_id": "slide_002",
        "main_title": "Second title",
        "visual_groups": [
            {"id": "slide_002_el_001", "role": "diagram", "visual_type": "illustration", "visual_anchor": "Beta"}
        ],
    },
]
batch_prompt = server.compose_step3_batch_copy_prompt("UNIQUE_GLOBAL_STYLE", sample_slides)
assert batch_prompt.count("UNIQUE_GLOBAL_STYLE") == 1
assert "slide_001" in batch_prompt and "slide_002" in batch_prompt
assert "First title" in batch_prompt and "Second title" in batch_prompt
assert "element_id" not in batch_prompt
assert "must not enter image input" not in batch_prompt
assert batch_prompt.count("<NonOverridableProductionRules>") == 1
assert "step3BatchPrompt" in app

minimal_input = server.step3_slide_input_payload(sample_slides[0])
assert minimal_input == {
    "slide_id": "slide_001",
    "main_title": "First title",
    "body_elements": [{"type": "text", "content": "Alpha"}],
}
assert write_visual_prompts.compact_visual_input(sample_slides[0]) == minimal_input
single_prompt = server.compose_step3_single_slide_prompt("STYLE", sample_slides[0], "CUSTOM SYSTEM")
assert "CUSTOM SYSTEM" in single_prompt
assert "First title" in single_prompt and "Alpha" in single_prompt
assert single_prompt.count("<NonOverridableProductionRules>") == 1
assert server.enforce_white_generation_background(single_prompt) == single_prompt

minimal_style = server.build_image_style_prompt(server.read_style_tokens_data())
assert "只描述视觉语言，不重复生产规则" in minimal_style
assert "narration beat" not in minimal_style
assert "visual_group" not in minimal_style
assert "副标题" not in minimal_style
assert len(minimal_style) < 1200

with tempfile.TemporaryDirectory() as temp_dir:
    project = SimpleNamespace(run_dir=temp_dir)
    server.write_step3_image_system_content(project, "PROJECT CUSTOM PROMPT")
    assert server.read_step3_image_system_content(project) == "PROJECT CUSTOM PROMPT"

print("prompt and thumbnail checks passed")
