from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
server = (ROOT / "server.py").read_text(encoding="utf-8")
app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
visual_prompts = (ROOT / "scripts" / "write_visual_prompts.py").read_text(encoding="utf-8")
style_tokens = yaml.safe_load((ROOT / "config" / "style_tokens.yaml").read_text(encoding="utf-8"))

assert 'IMAGE_GENERATION_BACKGROUND = "#FFFFFF"' in server
assert 'DEFAULT_VIDEO_BACKGROUND = "#FEFDF9"' in server
assert "/steps/3/visual-settings" in server
assert "connected_content_alpha" in server
assert style_tokens["canvas"]["background"] == "#FFFFFF"
assert style_tokens["visual_assets"]["required_background"] == "flat_uniform_pure_white"
assert "pure-white #FFFFFF background" in visual_prompts
assert "step3-video-background-color" in html
assert "step3-video-background-text" in html
assert "step3-video-background-apply" in html
assert "saveStep3VideoBackground" in app

print("white background workflow checks passed")
