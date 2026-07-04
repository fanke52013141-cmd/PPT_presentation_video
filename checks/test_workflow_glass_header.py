from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

assert ".step2-sticky-header::before" in css
assert ".step3-toolbar-row::before" in css
assert ".step5-mask-header::before" in css
assert ".step6-compact-header::before" in css
assert "backdrop-filter: saturate(135%) blur(24px)" in css
assert "background: rgba(250, 251, 255, 0.018)" in css
assert "mask-image: linear-gradient(" in css
assert "rgba(0, 0, 0, 0.34) 84%" in css
assert "transparent 100%" in css
assert "border-bottom: 1px solid rgba(215, 221, 235" not in css
assert "border-radius: 0" in css
assert "box-shadow: none !important" in css

print("workflow glass header checks passed")
