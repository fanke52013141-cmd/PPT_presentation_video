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
    assert "字幕文件（SRT）" in html
    assert "/subtitles/readiness" in script
    assert "/subtitles.srt" in script
    assert "downloadStep8Subtitles" in script
    assert "label: '作品输出'" in flow
