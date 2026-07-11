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
assert 'id="ai-mask-full-prompt"' in mask_ui
full_mask_prompt = mask._compose_ai_mask_full_prompt("method", "schema")
assert "method" in full_mask_prompt and "schema" in full_mask_prompt
assert "OUTPUT STRUCTURE / 输出结构" in full_mask_prompt
assert ".slide-thumbnail-card.step2-slide-thumb" in css
assert "height: 32px !important" in css

script_prompt = (ROOT / "templates" / "prompts" / "step2_script_system.md").read_text(encoding="utf-8")
visual_prompt = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
image_prompt = (ROOT / "templates" / "prompts" / "visual_draft.prompt.md").read_text(encoding="utf-8")
assert "body_points" in script_prompt
assert "narration_segments" in script_prompt
assert "视觉岛" in visual_prompt
assert "48-80 px" in image_prompt

print("prompt and thumbnail checks passed")
