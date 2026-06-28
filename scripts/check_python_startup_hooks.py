"""Ensure normal startup uses explicit runtime installation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert "runtime_bootstrap.install_for_server_module" in server
    assert "def install_for_server_module" in bootstrap
    assert not (ROOT / "usercustomize.py").exists()
    print("python startup hook contract passed")


if __name__ == "__main__":
    main()
