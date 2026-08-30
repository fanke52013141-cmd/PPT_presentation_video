# 2026-08-31 代码审查跟进

## 范围

根据桌面版 `code_review_report.html` 对当前版本源码逐项复核，只处理能够在当前代码中确认、且不会改变已稳定业务流程的问题。

## 已处理

- ComfyUI 数字人工作流文件损坏时，生成请求不再静默忽略模板；接口会返回可操作的 409 错误。
- 数字人工作流状态接口增加 `valid` 字段，便于前端识别文件存在但不可用的情况。
- 旁白初始化校验分镜规划和单页旁白 JSON；文件损坏或结构错误时返回明确错误。
- 旁白生成子进程失败时同时记录 stdout 和 stderr，保留最多 4000 个字符的诊断信息。
- Mask 全屏画布移除永久 800ms 轮询，改用窗口 resize 和全屏状态变化监听。
- 竖屏视频审查预览继续使用视口约束和 `object-fit: contain`，保证一屏能看到完整视频。

## 复核结论

- 报告中的数据库回滚、AI Mask 视觉失败日志、一键流程 step_status 回滚等问题在当前版本已经存在对应处理，不重复改造。
- 语义匹配器、组件检测缓存和图片文件删除处的异常回退属于有意的容错路径，本轮不改变行为。
- innerHTML 使用、渲染并发策略、全局依赖注入和提示文案统一属于后续专项优化，不在本次稳定性修复中进行高风险重构。

## 验证

- `python -m pytest checks -q`：332 passed（1 个第三方弃用警告）
- `node checks/test_frontend_quality.js`：通过
- `node checks/test_mask_zoom_coordinates.js`：通过
- `node checks/test_visible_flow.js`：通过
- `scripts/remotion/node_modules/.bin/tsc.cmd --noEmit -p scripts/remotion/tsconfig.json`：通过
- 本地项目 HTTP 根页面、`/api/settings`、`/api/projects` 冒烟检查通过

ComfyUI 8188 服务在本次推送时未运行，因此未执行真实数字人合成；本次修改只涉及项目侧请求校验、错误反馈和前端画布适配。
