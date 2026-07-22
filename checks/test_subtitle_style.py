from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
video = (ROOT / "scripts" / "remotion" / "src" / "Video.tsx").read_text(encoding="utf-8")
style_tokens = yaml.safe_load((ROOT / "config" / "style_tokens.yaml").read_text(encoding="utf-8"))
overlay = style_tokens["subtitle"]["overlay"]

# 保留原字体相关断言
assert "bottom: subtitleStyle?.bottom ?? 18" in video
assert "subtitleStyle?.font_size ?? 38" in video  # 主路径 SubtitleView 和 fallback 都有此表达式
assert "subtitleFontFamily" in video
assert '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif' in video
assert "@remotion/google-fonts/NotoSansSC" in video
assert "loadNotoSansSC" in video
assert "background: 'transparent'" in video
assert "rgba(255, 253, 247, 0.82)" not in video
assert overlay["background"] == "transparent"
assert overlay["border_radius"] == 0
assert overlay["bottom"] == 18

# 方案 B：TikTok 式整页分页 + 逐字高亮 必须存在
assert "buildCaptionPages" in video, "buildCaptionPages 函数缺失"
assert "pageAtTime" in video, "pageAtTime 函数缺失"
assert "highlightedTokenCount" in video, "highlightedTokenCount 函数缺失"
assert "splitSentenceToTokens" in video, "splitSentenceToTokens 函数缺失"
assert "SubtitleView" in video, "SubtitleView 组件缺失"
# 不再使用单 segment 直接显示作为主路径
assert "subtitleAtTime" in video, "fallback 函数 subtitleAtTime 仍需保留"

# CSS 关键属性：分页器控量、词内不切断、保留空格，主路径不得裁字
assert "subtitleTextCapacity" in video, "必须根据字号、边距和最大行数计算每页容量"
assert "splitSegmentForCapacity" in video, "超长单句必须支持安全拆页"
assert "overflow: 'visible'" in video, "主字幕路径不得隐藏溢出文字"
assert "wordBreak: 'keep-all'" in video, "wordBreak 必须为 keep-all 防止词内切断"
assert "whiteSpace: 'pre-wrap'" in video, "whiteSpace 必须为 pre-wrap 保留空格"
assert "overflowWrap: 'normal'" in video, "overflowWrap 必须为 normal 不允许任意位置折断"
# 旧的"任意位置折断"必须被移除
assert "overflowWrap: 'anywhere'" not in video, "overflowWrap: 'anywhere' 已被弃用"

# 新增 SubtitleStyle 字段必须在类型定义里
assert "highlight_color?: string" in video, "SubtitleStyle.highlight_color 字段缺失"
assert "paging_window_ms?: number" in video, "SubtitleStyle.paging_window_ms 字段缺失"
assert "token_highlight?: boolean" in video, "SubtitleStyle.token_highlight 字段缺失"
assert "max_lines?: number" in video, "SubtitleStyle.max_lines 字段缺失"
assert "line_height?: number" in video, "SubtitleStyle.line_height 字段缺失"

# style_tokens.yaml 同步声明新字段
assert overlay["highlight_color"] == "#1E3A8A"
assert overlay["paging_window_ms"] == 1300
assert overlay["token_highlight"] is True
assert overlay["line_height"] == 1.4

# build_remotion_props.py 的 DEFAULT_SUBTITLE_STYLE 必须同步
build_props = (ROOT / "scripts" / "build_remotion_props.py").read_text(encoding="utf-8")
assert '"highlight_color": "#1E3A8A"' in build_props
assert '"paging_window_ms": 1300' in build_props
assert '"token_highlight": True' in build_props
assert '"max_lines": 2' in build_props
assert '"line_height": 1.4' in build_props

print("subtitle style checks passed")
