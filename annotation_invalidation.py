# -*- coding: utf-8 -*-
"""勾画标注的业务失效(W4,交接文档 8.2 失效矩阵的落点)。

由 ``invalidation_service`` 与旁白持久化路径显式调用;本模块不做路由、
不提交数据库,只操作勾画自己的产物与页面文件(项目锁由调用方持有,
或通过传入的 lock 工厂获取)。

矩阵节选:
- 图片替换/删除:删 text_layout/annotation_timeline,启用条目
  spatial→stale、content→draft(确认失效);人工几何与锁定证据保留。
- 讲稿修改:锚定条目 temporal→stale、content→draft;空间与样式保留。
- 音频重生成:对齐/时间确认/事件失效(temporal→awaiting_audio);
  空间、样式、讲稿关联保留。
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, List, Optional, Tuple

from annotation_store import AnnotationStore

logger = logging.getLogger("PPTStudio.AnnotationInvalidation")


def invalidate_for_layout_correction(project, slide_id, layout, changed_token_ids, *, store, canvas):
    """Correct selected screen text without discarding unrelated items or audio."""
    from annotation_target_resolver import resolve_phrase_target
    from datetime import datetime, timezone

    page = store.read_page(str(project.run_dir), slide_id, canvas=canvas)
    if page is None:
        return False
    updated, changed, active_changed = [], False, False
    for item in page.items:
        if item.target.kind != "text" or not set(item.target.token_ids).intersection(changed_token_ids):
            updated.append(item)
            continue
        resolved = resolve_phrase_target(layout=layout, token_ids=item.target.token_ids)
        review_issues = [issue for issue in item.review_issues if issue.get("code") not in {"ocr_text_uncertain", "screen_narration_mismatch"}]
        if any(marker in resolved["screen_quote"] for marker in ("▣", "�", "\ufffc")):
            review_issues.append({"code": "ocr_text_uncertain", "message": "画面文字仍含未识别字符，请核对 OCR"})
        if item.anchor and item.anchor.quote != resolved["screen_quote"]:
            review_issues.append({"code": "screen_narration_mismatch", "message": "画面文字与讲稿用词不同，请核对对应关系"})
        status = item.status if item.status.content == "disabled" else replace(item.status, content="draft", spatial="needs_review")
        updated.append(replace(item, target=replace(item.target, quote=resolved["screen_quote"]),
            status=status, confirmed_inputs=None,
            protection=replace(item.protection, modified_fields=tuple(sorted(set(item.protection.modified_fields) | {"target"}))),
            review_issues=tuple(review_issues)))
        changed = True
        active_changed = active_changed or item.status.content != "disabled"
    if not changed:
        return False
    store.write_page(str(project.run_dir), slide_id, replace(page, revision=page.revision + 1, items=tuple(updated),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    if active_changed:
        _timeline_file(str(project.run_dir), slide_id).unlink(missing_ok=True)
    return active_changed


def _page_path(run_dir: str, slide_id: str) -> Path:
    from project_storage import slide_file

    return Path(slide_file(run_dir, slide_id, "annotations.json"))


def _layout_file(run_dir: str, slide_id: str) -> Path:
    from project_storage import slide_file

    return Path(slide_file(run_dir, slide_id, "text_layout.json"))


def _timeline_file(run_dir: str, slide_id: str) -> Path:
    from project_storage import slide_file

    return Path(slide_file(run_dir, slide_id, "annotation_timeline.json"))


def _remove(path: Path, removed: List[Path]) -> None:
    try:
        path.unlink()
        removed.append(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Failed to remove annotation artifact %s: %s", path, exc)


def invalidate_for_image_change(
    project: Any,
    slide_id: str,
    store: Optional[AnnotationStore] = None,
    canvas: Tuple[int, int] = (1920, 1080),
) -> List[Path]:
    """图片替换/删除后的勾画失效;返回被删除/更新的产物路径。"""
    removed: List[Path] = []
    run_dir = str(project.run_dir)
    _remove(_layout_file(run_dir, slide_id), removed)
    _remove(_timeline_file(run_dir, slide_id), removed)
    store = store or _default_store()
    if store is None:
        return removed
    try:
        page = store.read_page(run_dir, slide_id, canvas=canvas)
    except Exception as exc:
        logger.warning("Skip annotation stale-marking for %s/%s: %s", run_dir, slide_id, exc)
        return removed
    if page is None or not page.items:
        return removed
    from annotation_contracts import AnnotationStatus

    updated = []
    for item in page.items:
        if item.status.content == "disabled":
            updated.append(item)
            continue
        updated.append(
            replace(
                item,
                status=AnnotationStatus(content="draft", spatial="stale", temporal=item.status.temporal),
                confirmed_inputs=None,
            )
        )
    from dataclasses import replace as _replace
    from datetime import datetime, timezone

    new_page = _replace(
        page,
        revision=page.revision + 1,
        items=tuple(updated),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    store.write_page(run_dir, slide_id, new_page)
    removed.append(_page_path(run_dir, slide_id))
    return removed


def invalidate_for_narration_change(
    project: Any,
    slide_id: str,
    store: Optional[AnnotationStore] = None,
    canvas: Tuple[int, int] = (1920, 1080),
) -> List[Path]:
    """讲稿修改后的勾画失效:锚定条目确认失效、时间置 stale;空间样式保留。"""
    removed: List[Path] = []
    run_dir = str(project.run_dir)
    _remove(_timeline_file(run_dir, slide_id), removed)
    store = store or _default_store()
    if store is None:
        return removed
    try:
        page = store.read_page(run_dir, slide_id, canvas=canvas)
    except Exception as exc:
        logger.warning("Skip annotation stale-marking for %s/%s: %s", run_dir, slide_id, exc)
        return removed
    if page is None or not page.items:
        return removed
    from annotation_contracts import AnnotationStatus

    changed = False
    updated = []
    for item in page.items:
        if item.status.content == "disabled" or item.anchor is None:
            updated.append(item)
            continue
        changed = True
        updated.append(
            replace(
                item,
                status=AnnotationStatus(content="draft", spatial=item.status.spatial, temporal="stale"),
                confirmed_inputs=None,
            )
        )
    if not changed:
        return removed
    from dataclasses import replace as _replace
    from datetime import datetime, timezone

    new_page = _replace(
        page,
        revision=page.revision + 1,
        items=tuple(updated),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    store.write_page(run_dir, slide_id, new_page)
    removed.append(_page_path(run_dir, slide_id))
    return removed


def invalidate_for_audio_change(
    project: Any,
    slide_id: str,
    store: Optional[AnnotationStore] = None,
    canvas: Tuple[int, int] = (1920, 1080),
) -> List[Path]:
    """音频重生成后的勾画失效:仅时间维度;空间、样式、讲稿关联保留。"""
    removed: List[Path] = []
    run_dir = str(project.run_dir)
    _remove(_timeline_file(run_dir, slide_id), removed)
    store = store or _default_store()
    if store is None:
        return removed
    try:
        page = store.read_page(run_dir, slide_id, canvas=canvas)
    except Exception as exc:
        logger.warning("Skip annotation stale-marking for %s/%s: %s", run_dir, slide_id, exc)
        return removed
    if page is None or not page.items:
        return removed
    from annotation_contracts import AnnotationStatus

    changed = False
    updated = []
    for item in page.items:
        timing = item.timing
        if timing.trigger_mode == "manual":
            timing = replace(timing, calibration_stale=True)
        if item.status.temporal == "awaiting_audio" and timing == item.timing:
            updated.append(item)
            continue
        changed = True
        updated.append(
            replace(
                item,
                status=AnnotationStatus(content="disabled" if item.status.content == "disabled" else "draft",
                                        spatial=item.status.spatial, temporal="awaiting_audio"),
                timing=timing,
                confirmed_inputs=None,
            )
        )
    if not changed:
        return removed
    from dataclasses import replace as _replace
    from datetime import datetime, timezone

    new_page = _replace(
        page,
        revision=page.revision + 1,
        items=tuple(updated),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    store.write_page(run_dir, slide_id, new_page)
    removed.append(_page_path(run_dir, slide_id))
    return removed


def _default_store() -> Optional[AnnotationStore]:
    try:
        from annotation_store import get_annotation_store

        return get_annotation_store()
    except Exception:
        pass
    # 组合根尚未配置单例时,退回与生产装配等价的无状态 store
    # (同一个 write_json_atomic 原子语义)。
    try:
        from annotation_store import AnnotationStore, AnnotationStoreDependencies
        from pipeline_lifecycle import write_json_atomic

        return AnnotationStore(AnnotationStoreDependencies(write_json_atomic=write_json_atomic))
    except Exception:
        return None
