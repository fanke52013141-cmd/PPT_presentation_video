"""Ensure normal startup uses explicit runtime installation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert "runtime_bootstrap.install_for_server_module" not in server
    assert "runtime_ai_mask._register" in server
    assert "runtime_bootstrap.install_when_server_ready" not in (ROOT / "database.py").read_text(encoding="utf-8")
    assert "def install_for_server_module" in bootstrap
    assert not (ROOT / "usercustomize.py").exists()
    print("explicit startup contract passed")


if __name__ == "__main__":
    main()
