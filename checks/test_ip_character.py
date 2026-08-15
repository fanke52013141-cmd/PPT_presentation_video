# -*- coding: utf-8 -*-
"""IP 形象提示词联动改造的静态契约检查。

验证：
1. ip_character_service.py 具备 prompt_template / prompt_text 字段与模板渲染能力
2. image_workflow_service.py 的提示词组装链路包含 IP 段并做去重
3. project_style_reference_service.py 支持 ip_prompt_segment 参数
4. 前端具备模板编辑与预览能力

不依赖完整服务运行，只做源码级断言。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ip_service = (ROOT / "ip_character_service.py").read_text(encoding="utf-8")
image_workflow = (ROOT / "image_workflow_service.py").read_text(encoding="utf-8")
style_ref = (ROOT / "project_style_reference_service.py").read_text(encoding="utf-8")
manager_js = (ROOT / "static" / "ip_character_manager.js").read_text(encoding="utf-8")
image_prompts_js = (ROOT / "static" / "image_prompts.js").read_text(encoding="utf-8")
index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

# ---- 1) ip_character_service.py ----
assert "IP_PROMPT_MARKER = \"<IPCharacterRequirements>\"" in ip_service
assert "DEFAULT_IP_PROMPT_TEMPLATE" in ip_service
assert "{characters}" in ip_service
assert 'def render_ip_character_prompt(project, slide_id=None):' in ip_service
assert '"prompt_template": DEFAULT_IP_PROMPT_TEMPLATE' in ip_service  # _empty_manifest
assert '"prompt_text": _safe_text(item.get("prompt_text"), 2000)' in ip_service  # 归一化
assert 'if "prompt_text" in payload:' in ip_service  # upsert 已有角色
assert '"prompt_text": _safe_text(payload.get("prompt_text"), 2000)' in ip_service  # upsert 新建
assert 'if "prompt_template" in payload:' in ip_service  # update_config
# render 函数逻辑：自定义提示词优先，留空自动生成
assert 'prompt_text = _safe_text(char.get("prompt_text"), 2000)' in ip_service
assert "entry = f\"{index}. {name}：{prompt_text}。建议位置：{position_label}。\"" in ip_service
# 兼容别名仍存在
assert 'def build_ip_character_prompt_segment(project, slide_id=None):' in ip_service
assert "return render_ip_character_prompt(project, slide_id)" in ip_service

# ---- 2) image_workflow_service.py ----
assert "from ip_character_service import (" in image_workflow
assert "IP_PROMPT_MARKER," in image_workflow
assert "render_ip_character_prompt," in image_workflow
# compose 单页/批量都支持 ip_prompt_segment
assert "ip_prompt_segment: str = \"\"" in image_workflow
assert image_workflow.count("ip_prompt_segment: str = \"\"") == 2
assert "if ip_prompt_segment:" in image_workflow
# 预览/设置接口返回 ip_prompt_segment 字段
assert '"ip_prompt_segment": render_ip_character_prompt(project, None)' in image_workflow
# 每页 prompt 注入 IP 段
assert "ip_prompt_segment=render_ip_character_prompt(project, slide_id)" in image_workflow
# 生图去重
assert "if ip_prompt_segment and IP_PROMPT_MARKER not in effective_prompt:" in image_workflow

# ---- 3) project_style_reference_service.py ----
assert "ip_prompt_segment: str = \"\"" in style_ref
assert "ip_prompt_segment," in style_ref  # 透传给 compose
assert "if ip_prompt_segment:" in style_ref  # legacy 分支追加
assert "project_generate_prompt_for_slide" in style_ref

# ---- 4) 前端 ----
# 角色卡片增加自定义提示词输入框
assert "ip-char-prompt" in manager_js
assert "自定义生图提示词（可选，留空自动生成）" in manager_js
# 保存角色时提交 prompt_text
assert "prompt_text: (promptText || \"\").trim()" in manager_js
# 模板编辑与恢复默认
assert "ip-character-prompt-template" in manager_js
assert "prompt_template: prompt_template" in manager_js
assert "btn-ip-character-reset-template" in manager_js
assert "DEFAULT_PROMPT_TEMPLATE" in manager_js
# index.html 有模板编辑区
assert 'id="ip-character-prompt-template"' in index_html
assert 'id="btn-ip-character-reset-template"' in index_html
assert "{characters}" in index_html
# 生图 Prompt 预览包含 IP 段
assert "ip_prompt_segment" in image_prompts_js
assert "=== IP 形象融入要求 ===" in image_prompts_js

print("ip character prompt-linkage checks passed")
