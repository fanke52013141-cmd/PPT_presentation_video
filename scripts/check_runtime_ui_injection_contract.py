#!/usr/bin/env python3
"""Self-check runtime UI injection bridges.

This check does not start the full FastAPI server. It imports the small runtime
UI bridges and exercises their string rewrite helpers against representative
HTML and JavaScript snippets. It catches regressions where browser cache-buster
versions drift apart or the Step 5 flush API stops being injected into app.js.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class CheckFailure(AssertionError):
    """Raised when the runtime UI injection contract fails."""


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def assert_contains(haystack: str, needle: str, context: str) -> None:
    assert_true(needle in haystack, f"{context}: missing {needle!r}")


def check_step5_flush_bridge() -> None:
    bridge = importlib.import_module("runtime_step5_flush_bridge")

    html = """
<html><body>
  <script src="flow.js?v=1.0.0"></script>
  <script src="app.js?v=2.14.0"></script>
  <script src="ai_mask_extension.js?v=20260626.1"></script>
</body></html>
"""
    rewritten_html = bridge._rewrite_html(html)
    assert_contains(rewritten_html, f"app.js?v={bridge.APP_SCRIPT_VERSION}", "Step 5 flush HTML rewrite")
    assert_contains(rewritten_html, f"ai_mask_extension.js?v={bridge.AI_MASK_SCRIPT_VERSION}", "Step 5 flush HTML rewrite")

    app_js = """
const state = { currentProject: null };
let manifestData = { slides: [{ slide_id: 'slide_001' }] };
async function runStep5SemanticBlocks() {
  return true;
}
"""
    rewritten_app_js = bridge._rewrite_app_js(app_js)
    for snippet in [
        bridge.APP_FLUSH_MARKER,
        "async function flushStep5Draft",
        "state.step5AutoSaveTimer",
        "state.step5AutoSavePromise",
        "saveStep5CurrentState();",
        "window.PPTStudio",
        "flushStep5Draft,",
    ]:
        assert_contains(rewritten_app_js, snippet, "Step 5 app.js flush injection")

    ai_mask_js = """
  async function flushStep5DraftBeforeAiMask() {
    await sleep(900);
  }

  function summarizeResult(result) {
    return result;
  }
"""
    rewritten_ai_mask_js = bridge._rewrite_ai_mask_js(ai_mask_js)
    for snippet in [
        bridge.AI_MASK_FLUSH_MARKER,
        "window.PPTStudio.flushStep5Draft",
        "source: 'ai-mask'",
        "Legacy fallback for older app.js",
        "function summarizeResult",
    ]:
        assert_contains(rewritten_ai_mask_js, snippet, "AI Mask flush rewrite")


def check_ai_mask_cache_buster() -> None:
    buster = importlib.import_module("runtime_ai_mask_ui_cache_buster")
    bridge = importlib.import_module("runtime_step5_flush_bridge")
    assert_true(
        buster.SCRIPT_VERSION == bridge.AI_MASK_SCRIPT_VERSION,
        "AI Mask cache-buster version must match Step 5 flush bridge AI_MASK_SCRIPT_VERSION",
    )

    html = '<html><body><script src="ai_mask_extension.js?v=20260626.1"></script></body></html>'
    rewritten = buster._rewrite_ai_mask_script(html)
    assert_contains(rewritten, f"ai_mask_extension.js?v={buster.SCRIPT_VERSION}", "AI Mask cache-buster rewrite")
    assert_true("20260626.1" not in rewritten, "AI Mask cache-buster must remove stale script version")

    blank_html = "<html><body></body></html>"
    injected = buster._rewrite_ai_mask_script(blank_html)
    assert_contains(injected, buster.SCRIPT_TAG, "AI Mask cache-buster injection")


def check_one_click_cache_buster() -> None:
    buster = importlib.import_module("runtime_one_click_ui_cache_buster")
    html = '<html><body><script src="one_click_extension.js?v=20260626.1"></script></body></html>'
    rewritten = buster._rewrite_one_click_script(html)
    assert_contains(rewritten, f"one_click_extension.js?v={buster.SCRIPT_VERSION}", "One-click cache-buster rewrite")
    assert_true("20260626.1" not in rewritten, "One-click cache-buster must remove stale script version")

    blank_html = "<html><body></body></html>"
    injected = buster._rewrite_one_click_script(blank_html)
    assert_contains(injected, buster.SCRIPT_TAG, "One-click cache-buster injection")


def check_static_entrypoint_mentions_app_js() -> None:
    index_html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert_contains(index_html, "app.js", "static/index.html")
    assert_contains(index_html, "flow.js", "static/index.html")


def main() -> int:
    checks = [
        check_static_entrypoint_mentions_app_js,
        check_step5_flush_bridge,
        check_ai_mask_cache_buster,
        check_one_click_cache_buster,
    ]
    try:
        for check in checks:
            check()
            print(f"PASS {check.__name__}")
    except CheckFailure as exc:
        print(f"FAIL {exc}")
        return 1
    except Exception as exc:  # defensive diagnostics
        print(f"FAIL unexpected error: {type(exc).__name__}: {exc}")
        return 1

    print(f"OK runtime UI injection contract passed ({len(checks)} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
