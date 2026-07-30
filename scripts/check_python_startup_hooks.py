"""Ensure normal startup uses explicit runtime installation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert not (ROOT / "sitecustomize.py").exists()
    assert "runtime_bootstrap.install_for_server_module" not in server
    assert "app.include_router(ai_mask_router)" in server
    assert "runtime_ai_mask._register" not in server
    assert "runtime_ai_mask_semantic_patch" not in server
    assert "vision_matcher=semantic_vision_matcher" in server
    assert "runtime_bootstrap.install_when_server_ready" not in (ROOT / "database.py").read_text(encoding="utf-8")
    assert not (ROOT / "runtime_bootstrap.py").exists()
    assert not (ROOT / "usercustomize.py").exists()
    print("explicit startup contract passed")


if __name__ == "__main__":
    main()
