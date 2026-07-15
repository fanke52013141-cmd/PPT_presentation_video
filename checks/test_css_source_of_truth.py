from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def active_frontend_sources() -> list[Path]:
    return [
        path
        for path in STATIC.iterdir()
        if path.suffix in {".html", ".js", ".css"} and not path.name.endswith(".bak")
    ]


def test_soft_pastel_styles_have_one_source_of_truth() -> None:
    sources = active_frontend_sources()
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    assert "sketch-" not in combined
    assert "style.textContent" not in combined
    assert "createElement('style')" not in combined
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "Soft Pastel Studio refinement layer" in css
    assert ".soft-outline" in css
    assert ".loading-spinner" in css
