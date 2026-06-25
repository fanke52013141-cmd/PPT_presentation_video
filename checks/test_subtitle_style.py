from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
video = (ROOT / "scripts" / "remotion" / "src" / "Video.tsx").read_text(encoding="utf-8")
style_tokens = yaml.safe_load((ROOT / "config" / "style_tokens.yaml").read_text(encoding="utf-8"))
overlay = style_tokens["subtitle"]["overlay"]

assert "bottom: subtitleStyle?.bottom ?? 18" in video
assert "fontSize: subtitleStyle?.font_size ?? 38" in video
assert "subtitleFontFamily" in video
assert '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif' in video
assert "@remotion/google-fonts" not in video
assert "minHeight: 54" in video
assert "background: 'transparent'" in video
assert "rgba(255, 253, 247, 0.82)" not in video
assert overlay["background"] == "transparent"
assert overlay["border_radius"] == 0
assert overlay["bottom"] == 18

print("subtitle style checks passed")
