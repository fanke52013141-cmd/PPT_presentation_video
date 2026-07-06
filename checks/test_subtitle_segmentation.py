#!/usr/bin/env python3
"""Regression checks for subtitle display segmentation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server as server_module
from scripts.minimax_tts import split_subtitles


def main() -> None:
    text = "，首先我们解释Token是什么，其次看它怎么计费。最后看上下文限制！"
    server_chunks = server_module.subtitle_chunks_for_timing(text)
    helper_chunks = split_subtitles(text, 18)

    assert server_chunks
    assert helper_chunks
    for chunk in server_chunks + helper_chunks:
        assert chunk == chunk.strip("，。！？；：、,.!?;: ")
        assert chunk[0] not in "，。！？；：、,.!?;:"
        assert chunk[-1] not in "，。！？；：、,.!?;:"

    assert any("首先我们解释Token是什么" in chunk for chunk in server_chunks)
    assert any("最后看上下文限制" in chunk for chunk in server_chunks)


if __name__ == "__main__":
    main()
