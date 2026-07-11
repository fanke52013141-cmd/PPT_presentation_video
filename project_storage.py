"""Safe, centralized filesystem paths for one project run directory."""

from __future__ import annotations

from pathlib import Path
import re


SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SAFE_VIDEO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,191}\.mp4$", re.IGNORECASE)


class UnsafeProjectPath(ValueError):
    pass


def project_root(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser().resolve()


def project_run_dir(runs_root: str | Path, run_dir: str | Path, project_id: str) -> Path:
    allowed_root = project_root(runs_root)
    candidate = project_root(run_dir)
    safe_project_id = safe_identifier(project_id, label="project_id")
    if candidate.parent != allowed_root or candidate.name != safe_project_id:
        raise UnsafeProjectPath(
            f"project run directory must be {allowed_root / safe_project_id}, got {candidate}"
        )
    return candidate


def safe_child(run_dir: str | Path, *parts: str | Path) -> Path:
    root = project_root(run_dir)
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeProjectPath(f"project path escapes run directory: {candidate}") from exc
    return candidate


def safe_identifier(value: str, *, label: str = "identifier") -> str:
    text = str(value or "").strip()
    if not SAFE_ID_PATTERN.fullmatch(text):
        raise UnsafeProjectPath(f"invalid {label}: {value!r}")
    return text


def safe_video_filename(value: str) -> str:
    text = str(value or "").strip()
    if not SAFE_VIDEO_PATTERN.fullmatch(text) or text in {".", ".."}:
        raise UnsafeProjectPath(f"invalid video filename: {value!r}")
    return text


def planning_path(run_dir: str | Path, filename: str) -> Path:
    safe_identifier(Path(filename).stem, label="planning filename")
    if Path(filename).name != filename or Path(filename).suffix not in {".json", ".txt", ".yaml", ".md"}:
        raise UnsafeProjectPath(f"invalid planning filename: {filename!r}")
    return safe_child(run_dir, "planning", filename)


def visual_contract_path(run_dir: str | Path) -> Path:
    return planning_path(run_dir, "visual_contract.json")


def reveal_manifest_path(run_dir: str | Path) -> Path:
    return safe_child(run_dir, "reveal_manifest.json")


def slide_dir(run_dir: str | Path, slide_id: str) -> Path:
    return safe_child(run_dir, "slides", safe_identifier(slide_id, label="slide_id"))


def slide_file(run_dir: str | Path, slide_id: str, filename: str) -> Path:
    if Path(filename).name != filename:
        raise UnsafeProjectPath(f"invalid slide filename: {filename!r}")
    return safe_child(slide_dir(run_dir, slide_id), filename)


def videos_dir(run_dir: str | Path) -> Path:
    return safe_child(run_dir, "videos")


def video_file(run_dir: str | Path, filename: str) -> Path:
    return safe_child(videos_dir(run_dir), safe_video_filename(filename))


def legacy_video_file(run_dir: str | Path) -> Path:
    return safe_child(run_dir, "out.mp4")


def video_sidecar(video_path: str | Path) -> Path:
    path = Path(video_path).resolve()
    if path.suffix.lower() != ".mp4":
        raise UnsafeProjectPath(f"video sidecar source must be an MP4: {video_path!r}")
    return Path(f"{path}.render.json")
