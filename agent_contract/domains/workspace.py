"""Agent workspace-domain declarations: courses, creation configs, one-click
controls and the storyboard background settings."""

from __future__ import annotations


from pydantic import BaseModel

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


def _cap(**kwargs) -> AgentCapability:
    kwargs.setdefault("version", "1.0")
    kwargs.setdefault("behavior_version", "1")
    kwargs.setdefault("status", CapabilityStatus.stable)
    kwargs.setdefault("request_model", BaseModel)
    kwargs.setdefault("response_model", BaseModel)
    kwargs["mcp_tool_name"] = "ppt_" + kwargs["id"].replace(".", "_")
    kwargs.setdefault("destructive", False)
    kwargs.setdefault("long_running", False)
    return AgentCapability(**kwargs)


CAPABILITIES = [
    # ---- 课程库 ----
    _cap(
        id="course.tree.get",
        description="Read the full course/chapter/project tree.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/courses/tree",
        cli_command="course tree",
        service_ref="course_routes.get_tree",
    ),
    _cap(
        id="course.reorder",
        description="Reorder courses with an ordered id list.",
        request_model=FreeFormRequest,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/courses/reorder",
        cli_command="course reorder",
        service_ref="course_routes.reorder_courses",
    ),
    _cap(
        id="chapter.reorder",
        description="Reorder chapters within one course.",
        request_model=FreeFormRequest,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/chapters/reorder",
        cli_command="chapter reorder",
        service_ref="course_routes.reorder_chapters",
    ),
    _cap(
        id="course.create",
        description="Create a course.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/courses",
        cli_command="course create",
        service_ref="course_routes.create_course",
    ),
    _cap(
        id="course.list",
        description="List courses.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/courses",
        cli_command="course list",
        service_ref="course_routes.list_courses",
    ),
    _cap(
        id="course.get",
        description="Read one course with its chapters.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/courses/{course_id}",
        cli_command="course show",
        service_ref="course_routes.get_course",
    ),
    _cap(
        id="course.update",
        description="Update course name/description.",
        request_model=FreeFormRequest,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/courses/{course_id}",
        cli_command="course --set",
        service_ref="course_routes.update_course",
    ),
    _cap(
        id="course.delete",
        description="Delete one course. Destructive.",
        destructive=True,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/courses/{course_id}",
        cli_command="course delete",
        service_ref="course_routes.delete_course",
    ),
    _cap(
        id="chapter.create",
        description="Create a chapter inside one course.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/courses/{course_id}/chapters",
        cli_command="chapter create",
        service_ref="course_routes.create_chapter",
    ),
    _cap(
        id="chapter.update",
        description="Update one chapter.",
        request_model=FreeFormRequest,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/chapters/{chapter_id}",
        cli_command="chapter --set",
        service_ref="course_routes.update_chapter",
    ),
    _cap(
        id="chapter.delete",
        description="Delete one chapter. Destructive.",
        destructive=True,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/chapters/{chapter_id}",
        cli_command="chapter delete",
        service_ref="course_routes.delete_chapter",
    ),
    _cap(
        id="chapter.move",
        description="Move one chapter to another course/position.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/chapters/{chapter_id}/move",
        cli_command="chapter move",
        service_ref="course_routes.move_chapter",
    ),
    _cap(
        id="project.move",
        description="Move one project into a course chapter.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/move",
        cli_command="project move",
        service_ref="course_routes.move_project",
    ),
    _cap(
        id="project.reorder",
        description="Reorder projects within one chapter.",
        request_model=FreeFormRequest,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/projects/reorder",
        cli_command="project reorder",
        service_ref="course_routes.reorder_projects",
    ),
    # ---- 创作配置包 ----
    _cap(
        id="config.list",
        description="List creation configuration packages (query: include_archived).",
        request_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/creation-configs",
        cli_command="config list",
        service_ref="creation_config_routes.list_creation_configs",
    ),
    _cap(
        id="config.default_payload.get",
        description="Read the default creation-config payload template.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/creation-configs/default-payload",
        cli_command="config default-payload",
        service_ref="creation_config_routes.get_default_creation_config_payload",
    ),
    _cap(
        id="config.create",
        description="Create a creation configuration package.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/creation-configs",
        cli_command="config create",
        service_ref="creation_config_routes.create_creation_config",
    ),
    _cap(
        id="config.import",
        description="Import a creation configuration package; every image reference is validated before any write.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/creation-configs/import",
        cli_command="config import",
        service_ref="creation_config_routes.import_creation_config",
    ),
    _cap(
        id="config.get",
        description="Read one creation configuration package.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/creation-configs/{package_id}",
        cli_command="config show",
        service_ref="creation_config_routes.get_creation_config",
    ),
    _cap(
        id="config.update",
        description="Update one creation configuration package.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/creation-configs/{package_id}",
        cli_command="config --set",
        service_ref="creation_config_routes.update_creation_config",
    ),
    _cap(
        id="config.version.get",
        description="Read one stored version of a creation configuration package.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/creation-configs/{package_id}/versions/{version}",
        cli_command="config version",
        service_ref="creation_config_routes.get_creation_config_version",
    ),
    _cap(
        id="config.copy",
        description="Copy one creation configuration package.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/creation-configs/{package_id}/copy",
        cli_command="config copy",
        service_ref="creation_config_routes.copy_creation_config",
    ),
    _cap(
        id="config.version.create",
        description="Snapshot the current package as a new version.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/creation-configs/{package_id}/versions",
        cli_command="config version-create",
        service_ref="creation_config_routes.create_creation_config_version",
    ),
    _cap(
        id="config.archive",
        description="Archive or restore one creation configuration package.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/creation-configs/{package_id}/archive",
        cli_command="config archive",
        service_ref="creation_config_routes.archive_creation_config",
    ),
    _cap(
        id="config.delete",
        description="Delete one creation configuration package. Destructive.",
        destructive=True,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/creation-configs/{package_id}",
        cli_command="config delete",
        service_ref="creation_config_routes.delete_creation_config",
    ),
    _cap(
        id="config.resolve",
        description="Resolve the effective creation configuration for a project with package overrides.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/creation-configs/{package_id}/resolve",
        cli_command="config resolve",
        service_ref="creation_config_routes.resolve_creation_config",
    ),
    # ---- 一键控制补充 ----
    _cap(
        id="pipeline.pause",
        description="Pause the active one-click pipeline run at the next safe boundary.",
        request_model=OptionalFreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/runs/latest/pause",
        cli_command="run pause",
        service_ref="one_click_routes.pause_one_click_route",
    ),
    _cap(
        id="pipeline.statuses.list",
        description="List all active one-click run statuses across projects.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/one-click-statuses",
        cli_command="run statuses",
        service_ref="one_click_routes.batch_one_click_status_route",
    ),
    # ---- 分镜背景设置 ----
    _cap(
        id="media.background_config.get",
        description="Read the storyboard video-background configuration (mode, color, image reference).",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard-background",
        cli_command="media background-config",
        service_ref="storyboard_background.get_background",
    ),
    _cap(
        id="media.background_config.update",
        description="Update the storyboard video-background configuration; prompts, manifest and Reveal assets are synchronized.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard-background",
        cli_command="media background-config --set",
        service_ref="storyboard_background.put_background",
    ),
    _cap(
        id="media.background_image.upload",
        description="Upload a custom storyboard background image (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard-background/image",
        cli_command="media background-image-upload",
        service_ref="storyboard_background.upload_background",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="media.background_image.get",
        description="Download the rendered storyboard background image as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard-background/image",
        cli_command="media background-image",
        service_ref="storyboard_background.get_background_image",
        transport="binary",
        mcp_enabled=False,
    ),
]
