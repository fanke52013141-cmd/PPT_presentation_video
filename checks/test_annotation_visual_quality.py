import pytest
from PIL import Image

from annotation_contracts import AnnotationStyle
from annotation_visual_quality import contrast_ratio, readable_ai_style


@pytest.mark.parametrize("background,kind", [
    ("#FFFFFF", "highlighter"), ("#FFE58A", "underline"), ("#202020", "underline"),
])
def test_ai_markers_remain_visible_on_paper_yellow_and_dark_backgrounds(tmp_path, background, kind):
    path = tmp_path / "slide.png"
    Image.new("RGB", (160, 90), background).save(path)
    default = AnnotationStyle(type="highlighter", color="#F6CE46", opacity=.28, width=5, padding=4, seed=0)
    style = readable_ai_style(path, [[[10, 10], [140, 10], [140, 40], [10, 40]]], default)
    assert style.type == kind
    if kind == "underline":
        rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        assert contrast_ratio(rgb(background), rgb(style.color)) >= 4.5
        assert style.opacity >= .9
    else:
        assert style == default


def test_unavailable_source_preserves_the_explicit_default(tmp_path):
    default = AnnotationStyle(type="highlighter", color="#F6CE46", opacity=.28, width=5, padding=4, seed=0)
    assert readable_ai_style(tmp_path / "missing.png", [], default) == default
