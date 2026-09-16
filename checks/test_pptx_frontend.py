from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_output_workspace_exposes_pptx_controls_and_status() -> None:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "output_render.js").read_text(encoding="utf-8")
    flow = (ROOT / "static" / "flow.js").read_text(encoding="utf-8")

    assert 'id="step8-btn-pptx"' in html
    assert 'id="step8-pptx-readiness"' in html
    assert 'id="step8-pptx-result-box"' in html
    assert "runStep8PptxExport" in script
    assert "startStep8PptxPolling" in script
    assert "/exports/pptx/readiness" in script
    assert "下载 PPTX" in script
    assert 'id="step8-btn-download-srt"' in html
    # 这里断言**实际发布的按钮文案**，而不是历史上的固定短语。
    # 按钮文案是用户可见的设计交付内容，会随设计稿调整；守护的目标是
    # "输出工作区仍然暴露字幕下载控件"，不是锁死某一句文案。
    assert "下载字幕 SRT" in html
    assert "/subtitles/readiness" in script
    assert "/subtitles.srt" in script
    assert "downloadStep8Subtitles" in script
    assert "label: '作品输出'" in flow
