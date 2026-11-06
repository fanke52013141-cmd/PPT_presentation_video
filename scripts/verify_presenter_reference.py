"""Generate real presenter verification inputs using the existing ComfyUI path.

Run explicitly; never imported by test discovery. Files live outside user projects.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-audio", type=Path, required=True)
    parser.add_argument("--tts-workflow", type=Path, required=True)
    parser.add_argument("--video-workflow", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--audio-only", action="store_true")
    args = parser.parse_args()
    from comfyui_backend import run_comfyui_inference, run_comfyui_tts

    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    audio = root / "narration.wav"
    text = (
        "大家好，欢迎来到今天的课堂。今天我们用一个简单的例子，理解如何把复杂的问题拆成清晰的步骤。"
        "首先，明确我们希望达成什么目标。然后，把任务分成几个能够检查的小环节。"
        "每完成一步，都停下来看看结果是否符合预期。不怕走得慢，关键是每一步都有依据。"
        "接下来，让我们一起开始练习。"
    )
    (root / "narration.txt").write_text(text, encoding="utf-8")
    if not audio.exists():
        run_comfyui_tts(text, args.reference_audio.resolve(), audio,
                       json.loads(args.tts_workflow.read_text(encoding="utf-8")), timeout=1800)
    if args.audio_only:
        print(str(audio), flush=True)
        return
    workflow = json.loads(args.video_workflow.read_text(encoding="utf-8"))
    # This is a verification input, not a change to the user's saved prompt.
    for node in workflow.values():
        if node.get("class_type") == "WanVideoTextEncode":
            node["inputs"]["positive_prompt"] = (
                "一位讲师正面自然讲课，保持输入照片的人物身份和服装，人物面部清晰，背景柔和虚化。"
                "根据音频自然口型同步，偶尔眨眼，轻微点头，固定镜头。"
            )

    def submitted(prompt_id: str) -> None:
        (root / "reference_prompt_id.txt").write_text(prompt_id, encoding="utf-8")
        print(f"Submitted original engine task: {prompt_id}", flush=True)

    # Unknown-result submissions are recovered by this exact prompt ID, never retried here.
    marker = root / "reference_prompt_id.txt"
    if marker.exists():
        from comfyui_backend import recover_comfyui_result
        result = recover_comfyui_result(marker.read_text(encoding="utf-8").strip(),
                                       root / "reference.mp4", workflow)
    else:
        result = run_comfyui_inference(args.image.resolve(), audio, root / "reference.mp4",
                                      workflow, timeout=14400, on_submitted=submitted)
    print(result, flush=True)


if __name__ == "__main__":
    main()
