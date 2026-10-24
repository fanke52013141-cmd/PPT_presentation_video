## Change

Describe the business behavior and affected feature IDs from `config/agent_features.json`.

## Agent contract

- Capability IDs and input/output or behavior changes:
- Contract/behavior revision and generated documents:
- Resource invalidation, permissions, idempotency and cancellation impact:
- If presentation-only, explain why the Agent contract is unaffected:

## 行为敏感面自检（审查报告 2026-10-24 G1：函数体内部变更不触发任何自动门禁）

- [ ] 本次**未改动**以下行为敏感服务的业务逻辑（生成、删除、确认、CAS/幂等语义、
      错误码、权限判定）：`project_service` / `storyboard_service` /
      `image_workflow_service` / `narration_service` / `tts_service` /
      `video_render_service` / `agent_idempotency_service` / `agent_api/auth` /
      `agent_contract/discovery` —— 若确未改动，本节剩余项可跳过
- [ ] 若有改动：受影响能力的 `behavior_version` 已递增
- [ ] 若有改动：已说明外部 Agent 可感知的行为差异（错误码/状态/副作用时机），
      必要时更新 `docs/agent/current-contract-guide.md`
- [ ] 若有改动：`AGENT_API_VERSION` 已递增且契约文档已同变更集再生成
      （`scripts/check_contract_version_discipline.py` 在 quick 检查中强制）

## Validation

List meaningful scenario tests and final check results. Newly added business operations must include an explicit Agent coverage decision; pending coverage blocks the final full-openness release.

- [ ] `python scripts/run_checks.py --level quick` 通过
- [ ] `python -m pytest checks/agent/ -q` 通过
