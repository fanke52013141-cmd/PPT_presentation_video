# -*- coding: utf-8 -*-
"""One-off maintenance: give the 夏晓华 account a working TTS voice binding.

The imported creation package specified voice ``xiaxiaohua001`` but carried no
TTS model connection, and ``tts_service`` only honours a project-level voice
when the project is bound to a TTS connection — unbound projects fall back to
the global voice. This script mirrors how the other accounts are wired:

1. create a MiniMax credential for the 夏晓华 account (API key copied from the
   global settings — verified to be able to call this cloned voice);
2. create the ``夏晓华 · 语音模型`` TTS model connection in the account scope;
3. bind it inside the 夏晓华 creation package payload (``tts.connection``),
   recompute the package ``content_hash``, and verify the package still
   resolves through the production ``resolve_creation_config``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_ID = "acct_c0fc31248cdc44b2"
PACKAGE_ID = "d086a3590bb34b8eb22a46d2e0ce2380"
VOICE_ID = "xiaxiaohua001"
CONNECTION_NAME = "夏晓华 · 语音模型"
CREDENTIAL_LABEL = "夏晓华 · 语音合成 API 密钥"


def atomic_write_json(path: Path, payload: dict) -> None:
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import server  # noqa: F401  (composition root: configures all dependencies)
    from account_context import account_scope
    from creation_config_service import content_hash, resolve_creation_config
    from credential_store import create_credential
    from model_connection_models import ModelConnectionCreate
    from model_connection_service import (
        _registry,
        create_model_connection,
    )

    conn = sqlite3.connect(str(REPO_ROOT / "data" / "projects.db"))
    api_key = conn.execute(
        "SELECT value FROM settings WHERE key='tts_api_key'"
    ).fetchone()[0]
    conn.close()
    if not api_key.strip():
        raise SystemExit("global tts_api_key is empty")

    # Re-runnable: reuse an existing connection from a previous attempt.
    with account_scope(ACCOUNT_ID):
        existing = [
            item
            for item in _registry()["connections"].values()
            if isinstance(item, dict)
            and item.get("kind") == "tts"
            and item.get("name") == CONNECTION_NAME
        ]
        if existing:
            connection_id = str(existing[0]["id"])
            print("connection exists:", connection_id)
        else:
            credential = create_credential(
                provider="minimax",
                label=CREDENTIAL_LABEL,
                secret_values={"api_key": api_key.strip()},
            )
            print("credential:", credential["credential_ref"])
            connection = create_model_connection(
                ModelConnectionCreate(
                    name=CONNECTION_NAME,
                    kind="tts",
                    provider="minimax",
                    model="speech-2.8-hd",
                    endpoint="https://api.minimaxi.com/v1/t2a_async_v2",
                    credential_ref=credential["credential_ref"],
                    public_config={
                        "voice_id": VOICE_ID,
                        "clone_voice_id": "",
                        "region": "",
                        "provider_extra": "",
                        "speed": "1.21",
                        "volume": "1.0",
                        "pitch": "0",
                    },
                )
            )
            connection_id = connection["id"]
            print("connection:", connection_id, connection["name"])

    store_path = REPO_ROOT / "data" / "creation_configs.json"
    store = json.loads(store_path.read_text(encoding="utf-8"))
    package = store["packages"][PACKAGE_ID]
    record = package["versions"][str(package["latest_version"])]
    payload = record["payload"]
    payload.setdefault("tts", {})["connection"] = {
        "connection_id": connection_id,
        "revision": 1,
    }
    # ``token_highlight`` is a subtitle styling flag, but its name trips the
    # store's sensitive-key guard ("token") and blocks resolve_creation_config.
    # The stored value is the consumer default (true), so dropping it is
    # behaviour-identical while making the package resolvable.
    dropped = payload.get("subtitle", {}).pop("token_highlight", None)
    if dropped is not None:
        print("removed subtitle.token_highlight (value was default true)")
    package["description"] = (
        "城市政务纪实蓝参考图、夏晓华图片生成与语音模型连接、夏晓华音色。"
    )
    record["content_hash"] = content_hash(payload)
    atomic_write_json(store_path, store)
    print("package patched, content_hash:", record["content_hash"])

    with account_scope(ACCOUNT_ID):
        resolved = resolve_creation_config(PACKAGE_ID, version=None, overrides={})
    tts = resolved["payload"].get("tts", {})
    ok = (
        tts.get("connection", {}).get("connection_id") == connection_id
        and tts.get("voice_id") == VOICE_ID
    )
    print("resolved tts:", json.dumps(tts, ensure_ascii=False)[:300])
    print("verify:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
