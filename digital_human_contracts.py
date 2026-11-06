"""Shared defaults for new presenter layouts; saved manual layouts are preserved."""

DEFAULT_CIRCLE = {"cx": 0.85, "cy": 0.76, "r": 0.12}


def digital_human_render_config(config: dict) -> dict:
    """Project only active composition settings; generation inputs stay separate."""
    if not config.get("enabled"):
        return {"enabled": False}
    result = {key: config.get(key) for key in (
        "enabled", "mode", "shape", "circle", "video", "position", "border",
    )}
    if config.get("mode") == "upload":
        result["upload_start_sec"] = config.get("upload_start_sec", 0)
        result["upload_short_video_policy"] = config.get("upload_short_video_policy", "reject")
    return result
