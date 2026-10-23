"""Canonical Agent model exports; domain modules own each schema exactly once.

The explicit imports below are the re-export surface consumed by
capabilities/dispatch/routes; ``__all__`` is collected from the domain
modules so a new schema needs no second registration here.
"""

import agent_contract.domains.accounts as _accounts
import agent_contract.domains.annotations as _annotations
import agent_contract.domains.article as _article
import agent_contract.domains.artifacts as _artifacts
import agent_contract.domains.audio as _audio
import agent_contract.domains.digital_human as _digital_human
import agent_contract.domains.freeform as _freeform
import agent_contract.domains.images as _images
import agent_contract.domains.mask as _mask
import agent_contract.domains.narration as _narration
import agent_contract.domains.outputs as _outputs
import agent_contract.domains.pipeline as _pipeline
import agent_contract.domains.project as _project
import agent_contract.domains.source as _source
import agent_contract.domains.storyboard as _storyboard
import agent_contract.domains.system as _system
import agent_contract.domains.video as _video
import agent_contract.domains.workflow as _workflow
from agent_contract.domains.article import (  # noqa: F401
    ArticleSettingsResult,
    ArticleSettingsUpdateRequest,
    ArticleSourceResult,
    ArticleSourceUpdateRequest,
)
from agent_contract.domains.artifacts import (  # noqa: F401
    ArtifactGetResult, ArtifactInfo, ArtifactsListRequest, ArtifactsListResult,
)
from agent_contract.domains.digital_human import (  # noqa: F401
    DigitalHumanConfigResult, DigitalHumanConfigUpdateRequest,
)
from agent_contract.domains.images import (  # noqa: F401
    ImageRegenerateRequest, ImageRegenerateResult,
)
from agent_contract.domains.narration import (  # noqa: F401
    NarrationUpdateRequest, TtsSynthesizeRequest, TtsSynthesizeResult,
)
from agent_contract.domains.pipeline import (  # noqa: F401
    CheckpointApproveRequest, CheckpointInfo, CheckpointListResult, CheckpointResult,
    PipelineResumeRequest, PipelineRunRequest, PipelineRunResult,
    PipelineStatusResult, StageGetResult,
)
from agent_contract.domains.project import (  # noqa: F401
    AutomationMode, CanvasProfile, ProductionMode, ProjectCreateRequest,
    ProjectCreateResult, ProjectDeleteRequest, ProjectDeleteResult, ProjectGetResult,
    ProjectListRequest, ProjectListResult, ProjectSummary, ProjectUpdateRequest,
    ProjectUpdateResult, PresentationMode, ReviewPolicy,
)
from agent_contract.domains.source import (  # noqa: F401
    SourceSetRequest, SourceSetResult,
)
from agent_contract.domains.storyboard import (  # noqa: F401
    Step2PromptTemplateDetailResult, Step2PromptTemplateListResult,
    Step2PromptTemplateSaveRequest, Step2PromptTemplateSaveResult,
    StoryboardComposeResult, StoryboardContractGetResult,
    StoryboardContractRepairResult, StoryboardContractUpdateRequest,
    StoryboardContractWriteResult, StoryboardPreviewResult,
    StoryboardProfilePatchRequest, StoryboardPromptsResult,
    StoryboardPromptsUpdateRequest, StoryboardRulesResult,
    StoryboardRulesUpdateRequest, StoryboardScriptExecuteRequest,
    StoryboardScriptPlanPayload, StoryboardScriptPlanResult,
    StoryboardSkeletonRequest, StoryboardSkeletonResult,
    StoryboardTemplateListResult, StoryboardTemplateSaveRequest,
    StoryboardTemplateSaveResult, StoryboardVisualPlanPayload,
    StoryboardVisualPlanResult,
)
from agent_contract.domains.system import (  # noqa: F401
    DiagnosticsResult, GenerationControlResult, GenerationKind,
    GenerationStopRequest, GenerationStopResult, IdentityResult,
)
from agent_contract.domains.video import (  # noqa: F401
    VideoRenderRequest, VideoRenderResult,
)
from agent_contract.domains.workflow import (  # noqa: F401
    ProjectStateResult,
)

_DOMAIN_MODULES = (
    _accounts, _annotations, _article, _artifacts, _audio, _digital_human,
    _freeform, _images, _mask, _narration, _outputs, _pipeline, _project,
    _source, _storyboard, _system, _video, _workflow,
)

__all__ = sorted({
    name
    for _module in _DOMAIN_MODULES
    for name, value in vars(_module).items()
    if not name.startswith("_")
    and getattr(value, "__module__", None) == _module.__name__
    and isinstance(value, type)
})
