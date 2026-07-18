from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as ai_mask
import server
from scripts.style_agent import style_bundle_system_prompt


def assert_contract(name: str, text: str) -> None:
    normalized = text.lower()
    purpose = ("## 目的" in text) or ("## purpose" in normalized)
    prompt_input = ("## 输入" in text) or ("## input" in normalized)
    output = ("## 输出" in text) or ("## output" in normalized)
    assert purpose, f"{name} is missing an explicit purpose section"
    assert prompt_input, f"{name} is missing an explicit input section"
    assert output, f"{name} is missing an explicit output section"


def main() -> None:
    prompt_files = [
        "narration.prompt.md",
        "scene_reconstruction.prompt.md",
        "slide_plan.prompt.md",
        "step2_script_system.md",
        "step2_visual_system.md",
        "visual_draft.prompt.md",
    ]
    for filename in prompt_files:
        text = (ROOT / "templates" / "prompts" / filename).read_text(encoding="utf-8")
        assert_contract(filename, text)

    assert_contract("article generation system prompt", server.DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT)
    assert_contract("style bundle system prompt", style_bundle_system_prompt())
    assert_contract("AI Mask system prompt", ai_mask.DEFAULT_METHODOLOGY)

    storyboard_system, _ = server.build_storyboard_request(
        "测试主题", "测试摘要", "测试正文", "遵守默认规则"
    )
    assert_contract("storyboard system prompt", storyboard_system)
    assert "只返回一个" in storyboard_system
    assert "合法 JSON" in storyboard_system
    assert "只输出合法 JSON" in style_bundle_system_prompt()


if __name__ == "__main__":
    main()
