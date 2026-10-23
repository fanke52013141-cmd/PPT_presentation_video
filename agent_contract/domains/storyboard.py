"""Agent storyboard (visible Step 2) request and response contracts.

计划/合约载荷（slides、visual_elements、contract）由业务规划层
（storyboard_planning / visual_contract_service）归一化校验；这里只声明
稳定的外层信封，不复制业务字段规则。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StoryboardProfilePatchRequest(BaseModel):
    """Rules/prompt-preview shared carrier: saved text or an ad-hoc profile patch."""

    rules: Optional[str] = None
    profile_yaml: Optional[str] = None
    profile_patch: Optional[Dict[str, Any]] = None


class StoryboardRulesUpdateRequest(StoryboardProfilePatchRequest):
    pass


class StoryboardRulesResult(BaseModel):
    success: bool
    rules: str
    profile_yaml: str
    schema_text: Optional[str] = None
    roles: Any = None
    editor: Any = None


class StoryboardPromptsUpdateRequest(BaseModel):
    script_system: Optional[str] = None
    script_output_example: Optional[str] = None
    visual_system: Optional[str] = None
    visual_output_example: Optional[str] = None


class StoryboardPromptsResult(BaseModel):
    success: bool
    prompts: Dict[str, str]
    defaults: Dict[str, str]
    compatibility: Any = None
    composed: Dict[str, str]


class StoryboardScriptExecuteRequest(BaseModel):
    requirement: Optional[str] = Field(None, description="本次演讲稿生成的补充要求")


class StoryboardScriptPlanPayload(BaseModel):
    slides: List[Dict[str, Any]] = Field(..., description="演讲稿规划页列表；字段由业务规划层校验")


class StoryboardScriptPlanResult(BaseModel):
    success: bool
    script_plan: Dict[str, Any]
    visual_exists: bool = False
    visual_stale: bool = False
    workflow_changed: bool = False
    workflow_pending: bool = False
    target_duration: Optional[Dict[str, Any]] = None


class StoryboardVisualPlanPayload(BaseModel):
    slides: List[Dict[str, Any]] = Field(..., description="可视化规划页列表；字段由业务规划层校验")


class StoryboardVisualPlanResult(BaseModel):
    success: bool
    visual_plan: Dict[str, Any]
    stale: bool = False


class StoryboardComposeResult(BaseModel):
    success: bool
    contract: Dict[str, Any]
    target_duration: Optional[Dict[str, Any]] = None


class StoryboardPreviewResult(BaseModel):
    success: bool
    system_content: str
    user_content: str


class StoryboardContractGetResult(BaseModel):
    success: bool
    message: Optional[str] = None
    contract: Optional[Dict[str, Any]] = None
    contract_sha256: Optional[str] = None
    target_duration: Optional[Dict[str, Any]] = None
    repair: Optional[Dict[str, Any]] = None


class StoryboardContractUpdateRequest(BaseModel):
    contract: Dict[str, Any] = Field(..., description="完整 Visual Contract 载荷；由业务规划层归一化校验")
    expected_contract_sha256: Optional[str] = Field(
        None, description="读取时返回的 CAS 基线；不匹配返回 409 且零副作用"
    )


class StoryboardContractWriteResult(BaseModel):
    success: bool
    contract: Dict[str, Any]
    contract_sha256: str
    validation: Dict[str, Any] = {}
    changed: bool = True


class StoryboardContractRepairResult(BaseModel):
    success: bool
    changed: bool
    contract: Dict[str, Any]


class StoryboardSkeletonSlide(BaseModel):
    slide_id: Optional[str] = None
    main_title: str
    narration: str


class StoryboardSkeletonRequest(BaseModel):
    slides: List[StoryboardSkeletonSlide] = Field(..., min_length=1)


class StoryboardSkeletonResult(BaseModel):
    success: bool
    contract: Dict[str, Any]
    ai_mode: str


class StoryboardTemplateSaveRequest(StoryboardProfilePatchRequest):
    name: str


class StoryboardTemplateListResult(BaseModel):
    success: bool
    templates: List[Dict[str, Any]] = []


class StoryboardTemplateSaveResult(BaseModel):
    success: bool
    template: Dict[str, Any]
    templates: List[Dict[str, Any]] = []


class Step2PromptTemplateSaveRequest(BaseModel):
    name: str
    prompt_type: str = Field("script", description="script 或 visual")
    script_system: Optional[str] = None
    script_output_example: Optional[str] = None
    visual_system: Optional[str] = None
    visual_output_example: Optional[str] = None


class Step2PromptTemplateListResult(BaseModel):
    success: bool
    templates: List[Dict[str, Any]] = []


class Step2PromptTemplateDetailResult(BaseModel):
    success: bool
    template: Dict[str, Any]


class Step2PromptTemplateSaveResult(BaseModel):
    success: bool
    template: Dict[str, Any]
    templates: List[Dict[str, Any]] = []
