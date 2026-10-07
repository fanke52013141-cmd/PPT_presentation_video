# -*- coding: utf-8 -*-
"""勾画标注模块的请求编排服务(W1:设置、页面读取、条目编辑)。

职责边界(交接文档第 4/5/8/9 节):

- 只做编排:账号/项目/slide 校验、revision CAS、操作合并、服务端输入
  哈希、原子发布。纯校验在 ``annotation_contracts``,文件读写与损坏诊断
  在 ``annotation_store``。
- 依赖显式注入(frozen record),不导入 server,不声明 APIRouter。
- 所有页面修改在项目级锁内完成"读取 → 校验 → 合并 → 原子写入 →
  revision+1";冲突返回 409 + 最新 revision,由路由层翻译。
- 输入哈希(image/narration/audio)一律服务端从真实文件计算,客户端
  不可伪造;W1 尚无音频接入,audio_hash 恒为 null。
"""
from __future__ import annotations
from annotation_contracts import EMPHASIS_LEVELS

import hashlib
import json
import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from account_context import get_current_account_id
from annotation_contracts import (
    DEFAULT_CANVAS,
    LIMITS,
    AnnotationItem,
    AnnotationPage,
    AnnotationSettings,
    AnnotationStatus,
    Issue,
    anchor_quote_matches,
    collect_issues,
    default_annotation_settings,
    next_annotation_id,
    page_item_counts,
)
from annotation_store import AnnotationStore, AnnotationStoreError
from annotation_prompt_templates import BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT
from database import Project
from project_storage import project_run_dir as validated_project_run_dir, slide_file
from repository_paths import RUNS_DIR
from visual_contract_service import read_contract_slide_ids

logger = logging.getLogger("PPTStudio.AnnotationService")

VISUAL_DRAFT_FILE = "visual_draft.png"
NARRATION_BEATS_FILE = "narration_beats.json"


def _default_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class AnnotationServiceDependencies:
    store: AnnotationStore
    lock_for: Callable[[Any], AbstractContextManager]
    now_iso: Callable[[], str] = _default_now_iso
    canvas: Tuple[int, int] = DEFAULT_CANVAS
    # W3:文字布局构建器与任务管理器;未配置时对应能力报 503。
    text_layout_builder: Any = None
    job_manager: Any = None
    ocr_ready: Callable[[], bool] = lambda: False
    # W3:规划 Prompt 存储(AnnotationPromptStore);未配置时 Prompt 端点报 503。
    prompt_store: Any = None
    prepare_playback: Any = None


class AnnotationService:
    def __init__(self, dependencies: AnnotationServiceDependencies):
        self._store = dependencies.store
        self._lock_for = dependencies.lock_for
        self._now_iso = dependencies.now_iso
        self._canvas = dependencies.canvas
        self._layout_builder = dependencies.text_layout_builder
        self._job_manager = dependencies.job_manager
        self._ocr_ready = dependencies.ocr_ready
        self._prompt_store = dependencies.prompt_store
        self._prepare_playback = dependencies.prepare_playback

    def _annotation_content_changed(self, project: Project, slide_ids: Sequence[str]) -> None:
        """Register the output-only consequence of a persisted annotation edit.

        The invalidation service owns the status transition and impact ledger.
        Keeping this call outside the annotation write lock avoids nesting the
        project artifact lock while still ensuring only successful writes can
        make an existing output stale.
        """
        from invalidation_service import annotation_content_changed

        annotation_content_changed(project, slide_ids)

    # ------------------------------------------------------------ 校验

    def _project_or_404(self, db: Session, project_id: str) -> Project:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.account_id == get_current_account_id())
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project

    def _run_dir(self, project: Project) -> str:
        return str(validated_project_run_dir(RUNS_DIR, project.run_dir, project.id))

    def _canvas_for(self, project: Project) -> Tuple[int, int]:
        profile_id = getattr(project, "canvas_profile", None)
        if not profile_id:
            return tuple(self._canvas)
        from canvas_profile_service import get_project_canvas

        canvas = get_project_canvas(project)
        return int(canvas["width"]), int(canvas["height"])

    def _slide_ids_or_404(self, project: Project) -> List[str]:
        slide_ids = read_contract_slide_ids(self._run_dir(project))
        if not slide_ids:
            raise HTTPException(status_code=404, detail="分镜规划尚未生成")
        return slide_ids

    def _slide_file(self, project: Project, slide_id: str, filename: str) -> Path:
        return Path(slide_file(self._run_dir(project), slide_id, filename))

    def _store_error_to_http(self, exc: AnnotationStoreError) -> HTTPException:
        if exc.code in ("corrupt", "schema"):
            return HTTPException(status_code=500, detail=f"勾画产物损坏,请检查 {exc.path}: {exc.message}")
        return HTTPException(status_code=500, detail=f"勾画产物读写失败: {exc.message}")

    # ------------------------------------------------------------ 输入哈希

    def _image_hash(self, project: Project, slide_id: str) -> Optional[str]:
        path = self._slide_file(project, slide_id, VISUAL_DRAFT_FILE)
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _narration_hash(self, project: Project, slide_id: str) -> Optional[str]:
        path = self._slide_file(project, slide_id, NARRATION_BEATS_FILE)
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _read_beats(self, project: Project, slide_id: str) -> List[Dict[str, Any]]:
        import json

        path = self._slide_file(project, slide_id, NARRATION_BEATS_FILE)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        beats = payload.get("beats") if isinstance(payload, dict) else None
        if not isinstance(beats, list):
            return []
        return [beat for beat in beats if isinstance(beat, dict)]

    # ------------------------------------------------------------ 摘要

    def get_summary(self, db: Session, project_id: str) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        run_dir = self._run_dir(project)
        try:
            stored = self._store.read_settings(run_dir)
        except AnnotationStoreError as exc:
            raise self._store_error_to_http(exc) from exc
        if stored is not None:
            settings = stored
        else:
            # 未使用状态对外统一为 revision 0(缺文件),与 update_settings
            # 的 CAS 基线一致;首次 PUT expected_revision=0 创建文件到 revision 1。
            settings = AnnotationSettings(
                revision=0,
                enabled=False,
                defaults=default_annotation_settings().defaults,
                updated_at="",
            )
        slide_ids = self._slide_ids_or_404(project)
        canvas = self._canvas_for(project)
        slides: List[Dict[str, Any]] = []
        pages: List[Any] = []
        for slide_id in slide_ids:
            try:
                page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            except AnnotationStoreError as exc:
                raise self._store_error_to_http(exc) from exc
            pages.append(page)
            slides.append({"slide_id": slide_id, "revision": page.revision if page else 0, "counts": page_item_counts(page)})
        return {
            "settings": settings.to_dict(),
            "slides": slides,
            "module_state": ("stale" if self._module_state(settings, pages) == "confirmed"
                             and not self._readiness(settings, run_dir, slide_ids, canvas)["can_render"]
                             else self._module_state(settings, pages)),
            "readiness": self._readiness(settings, run_dir, slide_ids, canvas),
        }

    def _module_state(self, settings: AnnotationSettings, pages: List[Any]) -> str:
        """模块六决策态(R2 方案 3.2):与 enabled 解耦。"""
        if settings.decision == "no_annotations":
            return "no_annotations"
        has_items = False
        all_confirmed = True
        has_stale = False
        for page in pages:
            for item in page.items if page else ():
                if item.status.content == "disabled":
                    continue
                has_items = True
                if item.status.spatial == "stale":
                    has_stale = True
                if item.status.content != "confirmed":
                    all_confirmed = False
        if not has_items:
            return "not_started"
        if has_stale:
            return "stale"
        if all_confirmed:
            return "confirmed"
        return "editing"

    def _readiness(self, settings: AnnotationSettings, run_dir: str, slide_ids: List[str], canvas: Tuple[int, int]) -> Dict[str, Any]:
        if not settings.enabled:
            return {"can_render": True, "reason": "", "blocking": []}
        try:
            pages = {sid: self._store.read_page(run_dir, sid, canvas=canvas) for sid in slide_ids}
        except AnnotationStoreError as exc:
            raise self._store_error_to_http(exc) from exc
        from annotation_build import AnnotationBuildError, validate_timeline
        blocking = []
        for slide_id, page in pages.items():
            active = [i for i in page.items if i.status.content != "disabled"] if page else []
            if not active:
                continue
            drafts = [i for i in active if i.status.content != "confirmed"]
            if drafts:
                blocking.extend({"slide_id": slide_id, "annotation_id": i.annotation_id, "reason": "unconfirmed"} for i in drafts)
                continue
            try:
                validate_timeline(Path(slide_file(run_dir, slide_id, "annotations.json")).parent, page, canvas=canvas)
            except AnnotationBuildError as exc:
                blocking.extend({"slide_id": slide_id, **issue} for issue in exc.issues)
        reason = "unconfirmed_items" if any(i["reason"] == "unconfirmed" for i in blocking) else "annotation_not_ready" if blocking else ""
        return {"can_render": not blocking, "reason": reason, "blocking": blocking}

    # ------------------------------------------------------------ 设置

    def update_settings(self, db: Session, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        run_dir = self._run_dir(project)
        expected_revision = payload.get("expected_revision")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise HTTPException(status_code=422, detail="expected_revision 必须是非负整数")
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=422, detail="enabled 必须是布尔")
        with self._lock_for(project):
            try:
                current = self._store.read_settings(run_dir)
            except AnnotationStoreError as exc:
                raise self._store_error_to_http(exc) from exc
            current_revision = current.revision if current else 0
            if expected_revision != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "revision_conflict", "current_revision": current_revision},
                )
            defaults = dict((current or default_annotation_settings()).defaults)
            raw_defaults = payload.get("defaults")
            if raw_defaults is not None:
                if not isinstance(raw_defaults, dict):
                    raise HTTPException(status_code=422, detail="defaults 必须是对象")
                defaults.update(raw_defaults)
            decision = (current.decision if current else "none") or "none"
            raw_decision = payload.get("decision")
            if raw_decision is not None:
                if raw_decision not in ("none", "no_annotations"):
                    raise HTTPException(status_code=422, detail="decision 必须是 none/no_annotations")
                decision = raw_decision
            baseline = current or default_annotation_settings()
            if (
                enabled == baseline.enabled
                and defaults == baseline.defaults
                and decision == baseline.decision
            ):
                return {
                    "revision": current_revision,
                    "enabled": baseline.enabled,
                    "defaults": baseline.defaults,
                    "decision": baseline.decision,
                }
            updated = AnnotationSettings(
                revision=current_revision + 1,
                enabled=enabled,
                defaults=defaults,
                updated_at=self._now_iso(),
                decision=decision,
            )
            try:
                self._store.write_settings(run_dir, updated)
            except AnnotationStoreError as exc:
                raise self._store_error_to_http(exc) from exc
        self._annotation_content_changed(project, self._slide_ids_or_404(project))
        return {
            "revision": updated.revision,
            "enabled": updated.enabled,
            "defaults": updated.defaults,
            "decision": updated.decision,
        }

    # ------------------------------------------------------------ 页面读取

    # ------------------------------------------------------------ W5: 正式笔迹(两端统一)

    def _item_strokes(self, run_dir: str, item: AnnotationItem, layout: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """派生条目的正式 v2 笔迹:编辑预览与导出共用同一实现。

        - 文字目标:layout + token_ids 经 target resolver 合成片段(同行连续
          合并、跨行拆分),逐片段生成手写笔迹;
        - 区域目标:每个多边形一个片段。
        生成失败返回空列表;调用方据此把 spatial 标记为 needs_review。
        """
        from annotation_geometry import FragmentInput, GeometryInputV2, build_manual_path_stroke, build_strokes_v2
        from annotation_target_resolver import TargetResolutionError, resolve_phrase_target

        from annotation_build import item_strokes
        try:
            return item_strokes(item, layout)
        except Exception as exc:
            logger.debug("stroke derivation failed for %s: %s", item.annotation_id, exc)
            return []

    def _items_with_strokes(self, run_dir: str, slide_id: str, items: Sequence[AnnotationItem]) -> List[Dict[str, Any]]:
        layout = None
        if self._layout_builder is not None:
            try:
                layout = self._layout_builder.load(run_dir, slide_id)
            except Exception:  # noqa: BLE001
                layout = None
        payloads: List[Dict[str, Any]] = []
        for item in items:
            payload = item.to_dict()
            payload["strokes"] = self._item_strokes(run_dir, item, layout)
            payloads.append(payload)
        return payloads

    def get_slide(self, db: Session, project_id: str, slide_id: str) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        slide_ids = self._slide_ids_or_404(project)
        if slide_id not in slide_ids:
            raise HTTPException(status_code=404, detail="Slide 不存在")
        run_dir = self._run_dir(project)
        canvas = self._canvas_for(project)
        try:
            page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            settings = self._store.read_settings(run_dir) or default_annotation_settings()
        except AnnotationStoreError as exc:
            raise self._store_error_to_http(exc) from exc
        beats = self._read_beats(project, slide_id)
        from annotation_build import read_json
        scene = read_json(self._slide_file(project, slide_id, "scene.json"), optional=True) or {}
        mask_groups = [{"id": layer["target_group_id"], "label": layer.get("visible_text") or layer["target_group_id"]}
                       for layer in scene.get("layers", []) if layer.get("target_group_id")]
        from annotation_build import file_hash
        from annotation_alignment import calibration_locator, calibration_audio_delay
        locator = calibration_locator(page.items if page else [],
            read_json(self._slide_file(project, slide_id, "word_alignment.json"), optional=True),
            audio_hash=file_hash(self._slide_file(project, slide_id, "voice.mp3")),
            narration_hash=self._narration_hash(project, slide_id))
        audio_timeline = read_json(self._slide_file(project, slide_id, "audio_timeline.json"), optional=True) or {}
        return {
            "audio_locator": locator,
            "audio_start_sec": calibration_audio_delay(audio_timeline),
            "mask_groups": mask_groups,
            "slide_id": slide_id,
            "revision": page.revision if page else 0,
            "items": self._items_with_strokes(run_dir, slide_id, page.items) if page else [],
            "ai_suggestion_snapshot": page.ai_suggestion_snapshot if page else None,
            "narration": {
                "hash": self._narration_hash(project, slide_id),
                "beats": [
                    {"beat_id": beat.get("id"), "spoken_text": str(beat.get("spoken_text") or "")}
                    for beat in beats
                ],
            },
            "image": {"hash": self._image_hash(project, slide_id)},
            "settings": {"enabled": settings.enabled},
            "layout": None,  # W3 文字布局层接入后填充
        }

    # ------------------------------------------------------------ 条目编辑

    def patch_slide(self, db: Session, project_id: str, slide_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        slide_ids = self._slide_ids_or_404(project)
        if slide_id not in slide_ids:
            raise HTTPException(status_code=404, detail="Slide 不存在")
        expected_revision = payload.get("expected_revision")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise HTTPException(status_code=422, detail="expected_revision 必须是非负整数")
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise HTTPException(status_code=422, detail="operations 必须是非空数组")
        if len(operations) > LIMITS["max_ops_per_request"]:
            raise HTTPException(status_code=413, detail=f"单次操作数超过 {LIMITS['max_ops_per_request']}")

        run_dir = self._run_dir(project)
        canvas = self._canvas_for(project)
        image_hash = self._image_hash(project, slide_id)
        narration_hash = self._narration_hash(project, slide_id)
        if image_hash is None:
            raise HTTPException(status_code=422, detail="当前页面缺少图片,请先在第三步生成或上传图片")
        if narration_hash is None:
            raise HTTPException(status_code=422, detail="当前页面缺少讲稿,请先完成旁白编辑")
        beats = {str(beat.get("id") or ""): beat for beat in self._read_beats(project, slide_id)}

        with self._lock_for(project):
            try:
                page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            except AnnotationStoreError as exc:
                raise self._store_error_to_http(exc) from exc
            current_revision = page.revision if page else 0
            if expected_revision != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "revision_conflict", "current_revision": current_revision},
                )

            items: List[AnnotationItem] = list(page.items) if page else []
            snapshot = page.ai_suggestion_snapshot if page else None
            issues: List[Issue] = []
            events: Dict[str, Any] = {}
            for index, operation in enumerate(operations):
                self._apply_operation(operation, items, beats, image_hash, narration_hash, issues, path=f"operations[{index}]", canvas=canvas, events=events)
                if len(items) > LIMITS["max_items_per_slide"]:
                    issues.append(Issue(f"operations[{index}]", "too_many", f"每页条目超过 {LIMITS['max_items_per_slide']}"))

            if issues:
                raise HTTPException(status_code=422, detail={"code": "validation_failed", "issues": collect_issues(issues)})

            page_changed = page is None or tuple(items) != page.items
            if page_changed:
                updated_page = AnnotationPage(
                    slide_id=slide_id,
                    revision=current_revision + 1,
                    items=tuple(items),
                    ai_suggestion_snapshot=snapshot,
                    updated_at=self._now_iso(),
                )
                try:
                    self._store.write_page(run_dir, slide_id, updated_page)
                except AnnotationStoreError as exc:
                    raise self._store_error_to_http(exc) from exc
                if events.get("confirmed_reset"):
                    # R4-004: 确认后内容被编辑,确认时刻派生的旧时间轴立即失效,
                    # 不得通过导出门禁;重新确认后将按新内容重建。
                    from project_storage import slide_file

                    Path(slide_file(run_dir, slide_id, "annotation_timeline.json")).unlink(missing_ok=True)
            else:
                updated_page = page
        if page_changed:
            self._annotation_content_changed(project, (slide_id,))
        return {
            "slide_id": slide_id,
            "revision": updated_page.revision,
            "items": self._items_with_strokes(run_dir, slide_id, updated_page.items),
        }

    def _apply_operation(
        self,
        operation: Any,
        items: List[AnnotationItem],
        beats: Dict[str, Dict[str, Any]],
        image_hash: Optional[str],
        narration_hash: Optional[str],
        issues: List[Issue],
        *,
        path: str,
        canvas: Tuple[int, int],
        events: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not isinstance(operation, dict):
            issues.append(Issue(path, "not_object", "操作必须是对象"))
            return
        op = operation.get("op")
        if op == "add":
            self._op_add(operation, items, beats, image_hash, narration_hash, issues, path=path, canvas=canvas)
        elif op == "update":
            self._op_update(operation, items, beats, issues, path=path, canvas=canvas, events=events)
        elif op == "delete":
            self._op_delete(operation, items, issues, path=path, events=events)
        elif op == "restore":
            self._op_restore(operation, items, beats, image_hash, narration_hash, issues, path=path, canvas=canvas)
        else:
            issues.append(Issue(f"{path}.op", "bad_enum", "op 必须是 add/update/delete/restore 之一"))

    def _validate_anchor(
        self,
        anchor_payload: Any,
        beats: Dict[str, Dict[str, Any]],
        issues: List[Issue],
        *,
        path: str,
    ):
        from annotation_contracts import AnnotationAnchor

        anchor = AnnotationAnchor.from_payload(anchor_payload, issues, path=path)
        if anchor is None:
            return None
        beat = beats.get(anchor.beat_id)
        if beat is None:
            issues.append(Issue(f"{path}.beat_id", "unknown_beat", f"讲稿语块 {anchor.beat_id} 不存在"))
            return anchor
        spoken = str(beat.get("spoken_text") or "")
        if not anchor_quote_matches(spoken, anchor):
            issues.append(
                Issue(f"{path}.quote", "quote_mismatch", "锚点文本与讲稿码点切片不一致")
            )
        if anchor.range_end > len(spoken):
            issues.append(Issue(f"{path}.range", "out_of_range", "锚点范围超出讲稿长度"))
        return anchor

    def _op_add(
        self,
        operation: Dict[str, Any],
        items: List[AnnotationItem],
        beats: Dict[str, Dict[str, Any]],
        image_hash: Optional[str],
        narration_hash: Optional[str],
        issues: List[Issue],
        *,
        path: str,
        canvas: Tuple[int, int],
    ) -> None:
        from annotation_contracts import AnnotationInputs, AnnotationProtection

        item_payload = operation.get("item")
        draft = AnnotationItem.from_payload(
            {"target": (item_payload or {}).get("target") if isinstance(item_payload, dict) else None,
             "anchor": (item_payload or {}).get("anchor") if isinstance(item_payload, dict) else None,
             "style": (item_payload or {}).get("style") if isinstance(item_payload, dict) else None,
             "timing": (item_payload or {}).get("timing") if isinstance(item_payload, dict) else None,
             "recommendation": (item_payload or {}).get("recommendation") if isinstance(item_payload, dict) else None},
            issues,
            canvas=canvas,
            path=f"{path}.item",
            require_id=False,
        )
        if draft is None:
            return
        anchor = None
        if draft.anchor is not None:
            anchor = self._validate_anchor(draft.anchor.to_dict(), beats, issues, path=f"{path}.item.anchor")
        if anchor is None and draft.target.kind == "text":
            issues.append(Issue(f"{path}.item.anchor", "required", "文字目标必须关联讲稿锚点"))
        spatial = "needs_review" if draft.target.granularity == "line" else "valid"
        item = AnnotationItem(
            annotation_id=next_annotation_id([i.annotation_id for i in items]),
            target=draft.target,
            anchor=anchor,
            style=draft.style,
            timing=draft.timing,
            status=AnnotationStatus(content="draft", spatial=spatial, temporal="awaiting_audio"),
            protection=AnnotationProtection(source="manual", modified_fields=(), locked=False),
            inputs=AnnotationInputs(
                image_hash=image_hash,
                narration_hash=narration_hash,
                audio_hash=None,
            ),
            recommendation=draft.recommendation,
        )
        items.append(item)

    def _op_update(
        self,
        operation: Dict[str, Any],
        items: List[AnnotationItem],
        beats: Dict[str, Dict[str, Any]],
        issues: List[Issue],
        *,
        path: str,
        canvas: Tuple[int, int],
        events: Optional[Dict[str, Any]] = None,
    ) -> None:
        from annotation_contracts import AnnotationProtection, AnnotationStatus, AnnotationTarget, AnnotationStyle, AnnotationTiming
        from dataclasses import replace

        annotation_id = operation.get("annotation_id")
        target_item = next((i for i in items if i.annotation_id == annotation_id), None)
        if target_item is None:
            issues.append(Issue(f"{path}.annotation_id", "unknown_id", f"条目 {annotation_id} 不存在"))
            return
        patch = operation.get("patch")
        if not isinstance(patch, dict) or not patch:
            issues.append(Issue(f"{path}.patch", "required", "patch 必须是非空对象"))
            return
        unknown = set(patch) - {"target", "anchor", "style", "timing", "protection", "status"}
        if unknown:
            issues.append(Issue(f"{path}.patch", "bad_field", f"不可识别的可编辑字段:{sorted(unknown)}"))
            return

        replacements: Dict[str, Any] = {}
        modified: List[str] = []
        if "target" in patch:
            new_target = AnnotationTarget.from_payload(patch["target"], issues, canvas=canvas, path=f"{path}.patch.target")
            if new_target is not None:
                if new_target.to_dict() != target_item.target.to_dict():
                    modified.append("target")
                replacements["target"] = new_target
        if "anchor" in patch:
            if patch["anchor"] is None:
                if target_item.target.kind == "text":
                    issues.append(Issue(f"{path}.patch.anchor", "required", "文字目标不能移除讲稿锚点"))
                else:
                    replacements["anchor"] = None
                    modified.append("anchor")
            else:
                anchor = self._validate_anchor(patch["anchor"], beats, issues, path=f"{path}.patch.anchor")
                if anchor is not None:
                    replacements["anchor"] = anchor
                    modified.append("anchor")
        if "style" in patch:
            new_style = AnnotationStyle.from_payload(patch["style"], issues, path=f"{path}.patch.style")
            if new_style is not None:
                if new_style.to_dict() != target_item.style.to_dict():
                    modified.append("style")
                replacements["style"] = new_style
        if "timing" in patch:
            new_timing = AnnotationTiming.from_payload(patch["timing"], issues, path=f"{path}.patch.timing")
            if new_timing is not None:
                # Old clients omitting the stale marker must not silently
                # approve a calibration made against replaced audio.
                if (target_item.timing.calibration_stale and new_timing.trigger_mode == "manual"
                        and patch["timing"].get("calibration_stale") is not False):
                    new_timing = replace(new_timing, calibration_stale=True)
                if new_timing.to_dict() != target_item.timing.to_dict():
                    modified.append("timing")
                replacements["timing"] = new_timing
        if "protection" in patch:
            raw_protection = patch["protection"]
            if not isinstance(raw_protection, dict) or set(raw_protection) - {"locked"}:
                issues.append(Issue(f"{path}.patch.protection", "bad_field", "保护字段仅允许修改 locked"))
            else:
                locked = raw_protection.get("locked")
                if isinstance(locked, bool):
                    replacements["protection"] = AnnotationProtection(
                        source=target_item.protection.source,
                        modified_fields=target_item.protection.modified_fields,
                        locked=locked,
                    )
                    modified.append("protection.locked")
        if "status" in patch:
            raw_status = patch["status"]
            if not isinstance(raw_status, dict) or set(raw_status) - {"content"}:
                issues.append(Issue(f"{path}.patch.status", "bad_field", "状态字段仅允许修改 content,且只能是 draft/disabled"))
            else:
                content = raw_status.get("content")
                if content in ("draft", "disabled"):
                    replacements["status"] = AnnotationStatus(
                        content=content,
                        spatial=target_item.status.spatial,
                        temporal=target_item.status.temporal,
                    )
                    modified.append("status.content")
                else:
                    issues.append(Issue(f"{path}.patch.status.content", "bad_enum", "确认状态只能通过确认接口设置"))

        if issues or not replacements:
            if not replacements and not issues:
                issues.append(Issue(f"{path}.patch", "empty", "patch 未产生任何修改"))
            return
        index = items.index(target_item)
        updated = replace(target_item, **replacements)
        # R4-004: 已确认条目的内容(target/anchor/style/timing)真实变化时,
        # 重置为 draft 并由调用方删除派生时间轴——旧笔迹不得通过导出门禁。
        # 相同值的保存不产生 modified,不触发重置;locked 等非像素变化同样豁免。
        if events is not None and "confirmed_reset" not in events:
            content_fields = {"target", "anchor", "style", "timing"}
            if modified and (content_fields & set(modified)) and updated.status.content == "confirmed":
                events["confirmed_reset"] = True
                updated = replace(
                    updated,
                    status=AnnotationStatus(
                        content="draft",
                        spatial=updated.status.spatial,
                        temporal=updated.status.temporal,
                    ),
                )
            elif "status.content" in modified and target_item.status.content == "confirmed":
                # 显式改 draft/disabled 同样使派生时间轴过期
                events["confirmed_reset"] = True
        if modified:
            merged = tuple(dict.fromkeys(target_item.protection.modified_fields + tuple(modified)))
            updated = replace(
                updated,
                protection=AnnotationProtection(
                    source=target_item.protection.source,
                    modified_fields=merged,
                    locked=updated.protection.locked,
                ),
            )
        items[index] = updated

    def _op_delete(
        self,
        operation: Dict[str, Any],
        items: List[AnnotationItem],
        issues: List[Issue],
        *,
        path: str,
        events: Optional[Dict[str, Any]] = None,
    ) -> None:
        annotation_id = operation.get("annotation_id")
        target_item = next((i for i in items if i.annotation_id == annotation_id), None)
        if target_item is None:
            issues.append(Issue(f"{path}.annotation_id", "unknown_id", f"条目 {annotation_id} 不存在"))
            return
        items.remove(target_item)
        # R4-004(B2): 删除已确认条目同样使派生时间轴失效,否则被删笔迹
        # 的墨迹帧仍会渲染进视频。
        if events is not None and target_item.status.content == "confirmed":
            events["confirmed_reset"] = True

    # ------------------------------------------------------------ W4: 确认门禁

    def prepare_slide(self, db, project_id, slide_id, payload, *, cancel_event=None, progress=None):
        from annotation_build import AnnotationBuildError, compile_slide, input_snapshot
        from pipeline_lifecycle import write_json_atomic
        project = self._project_or_404(db, project_id)
        if slide_id not in self._slide_ids_or_404(project):
            raise HTTPException(status_code=404, detail="Slide 不存在")
        if self._prepare_playback:
            if progress:
                progress(10, "reveal")
            self._prepare_playback(project, slide_id)
        canvas = self._canvas_for(project)
        directory = self._slide_file(project, slide_id, "annotations.json").parent
        with self._lock_for(project):
            page = self._store.read_page(self._run_dir(project), slide_id, canvas=canvas)
            revision = page.revision if page else 0
            expected = payload.get("expected_revision")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected != revision:
                raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": revision})
            if not page:
                raise HTTPException(status_code=422, detail={"code": "no_annotations"})
            before = input_snapshot(directory, page.items, canvas)
        try:
            if progress:
                progress(25, "target_check")
            compiled = compile_slide(directory, page, canvas=canvas,
                **({"cancel_event": cancel_event} if cancel_event else {}),
                **({"progress": progress} if progress else {}))
        except AnnotationBuildError as exc:
            raise HTTPException(status_code=422, detail={"code": "annotation_prepare_failed", "items": exc.issues}) from exc
        with self._lock_for(project):
            if cancel_event and cancel_event.is_set():
                raise HTTPException(status_code=409, detail={"code": "cancelled"})
            latest = self._store.read_page(self._run_dir(project), slide_id, canvas=canvas)
            if not latest or latest.revision != revision or input_snapshot(directory, latest.items, canvas) != before:
                raise HTTPException(status_code=409, detail={"code": "stale_input", "current_revision": latest.revision if latest else 0})
            write_json_atomic(directory / "annotation_preview.json", compiled)
        from annotation_build import read_json
        scene = read_json(directory / "scene.json", optional=True) or {
            "slide_id": slide_id, "canvas": {"width": canvas[0], "height": canvas[1], "background": "#FEFDF9"},
            "layers": [{"id": "full_slide", "type": "png", "role": "full_slide", "asset": "visual_draft.png",
                        "box": {"x": 0, "y": 0, "w": canvas[0], "h": canvas[1]}, "z_index": 0}],
        }
        return {"revision": revision, "timeline": compiled, "build_id": compiled.get("build_id"),
                "scene": scene, "animation_timeline": read_json(directory / "animation_timeline.json", optional=True) or {"events": []},
                "audio_timeline": read_json(directory / "audio_timeline.json", optional=True),
                "audio_url": f"/api/projects/{project_id}/slides/{slide_id}/audio"}

    def export_preview(self, db, project_id, slide_id, payload):
        from annotation_preview_export import export_preview
        if self._job_manager is None:
            raise HTTPException(503, "勾画任务引擎尚未配置")
        prepared = self.prepare_slide(db, project_id, slide_id, payload)
        source = self.preview_scene_asset(db, project_id, slide_id, "visual_draft.png").parent
        store = self._job_manager._deps.job_store
        job = store.create(project_id, job_type="annotation_preview", payload={"slide_id": slide_id, "export": True})
        store.mark_running(job.id, "render")
        try:
            token = export_preview(source, prepared, payload.get("subtitle_style"))
            from artifact_registry import record_artifact
            output = source / "preview_exports" / (token + ".mp4")
            record_artifact(db, project_id=project_id, artifact_type="annotation_preview_video",
                            path=output, relative_path=f"slides/{slide_id}/preview_exports/{token}.mp4",
                            mime_type="video/mp4", metadata={"slide_id": slide_id, "revision": prepared["revision"]})
            db.commit()
            store.mark_succeeded(job.id, "done", {"export_token": token})
        except Exception as error:
            store.mark_failed(job.id, str(error))
            raise
        return {"success": True, "url": f"/api/projects/{project_id}/annotations/slides/{slide_id}/export-preview/{token}"}

    def confirm_slide(self, db, project_id, slide_id, payload):
        from dataclasses import replace
        from annotation_build import input_snapshot, read_json
        from pipeline_lifecycle import write_json_atomic
        from project_impact_service import resolve_impacts, snapshot_impacts
        project = self._project_or_404(db, project_id)
        if slide_id not in self._slide_ids_or_404(project):
            raise HTTPException(status_code=404, detail="Slide 不存在")
        expected = payload.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise HTTPException(status_code=422, detail="expected_revision 必须是非负整数")
        accepted = payload.get("accepted_review") or []
        if not isinstance(accepted, list):
            raise HTTPException(status_code=422, detail="accepted_review 必须是数组")
        run_dir, canvas = self._run_dir(project), self._canvas_for(project)
        directory = self._slide_file(project, slide_id, "annotations.json").parent
        with self._lock_for(project):
            page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            revision = page.revision if page else 0
            if revision != expected:
                raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": revision})
            if not page or not page.items:
                raise HTTPException(status_code=422, detail={"code": "no_annotations"})
            blocked = [{"annotation_id": item.annotation_id, "reason": "review_required"}
                       for item in page.items if item.status.content != "disabled"
                       and (item.status.spatial == "needs_review" or item.review_issues)
                       and item.annotation_id not in accepted]
            if blocked:
                raise HTTPException(status_code=422, detail={"code": "review_required", "items": blocked})
        requested_build = payload.get("prepared_build_id")
        if requested_build:
            compiled = read_json(directory / "annotation_preview.json", optional=True)
            if not compiled or compiled.get("build_id") != requested_build:
                raise HTTPException(status_code=409, detail={"code": "stale_preview"})
        else:
            compiled = self.prepare_slide(db, project_id, slide_id, {"expected_revision": expected})["timeline"]
        impact = snapshot_impacts(run_dir, affected=("annotation geometry", "annotation timing"), slide_ids=(slide_id,))
        with self._lock_for(project):
            page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            if (not page or page.revision != expected
                    or any(compiled.get("inputs", {}).get(key) != value
                           for key, value in input_snapshot(directory, page.items, canvas).items())):
                raise HTTPException(status_code=409, detail={"code": "stale_preview", "current_revision": page.revision if page else 0})
            existing = read_json(directory / "annotation_timeline.json", optional=True)
            changed = existing != compiled or any(i.status.content not in ("confirmed", "disabled") for i in page.items)
            if changed:
                event_by_id = {event["annotation_id"]: event for event in compiled["events"]}
                items = tuple(replace(item, status=AnnotationStatus(
                    content="confirmed", spatial=item.status.spatial,
                    temporal="manual" if event_by_id[item.annotation_id]["timing_source"] == "manual" else "word_aligned"),
                    confirmed_inputs={**compiled["inputs"], "build_id": compiled.get("build_id"), "confirmed_at": self._now_iso()})
                    if item.status.content != "disabled" else item for item in page.items)
                page = replace(page, revision=page.revision + 1, items=items, updated_at=self._now_iso())
                # Publish only complete immutable assets; a crash between files is blocked by readiness.
                write_json_atomic(directory / "annotation_timeline.json", compiled)
                self._store.write_page(run_dir, slide_id, page)
        if changed:
            self._annotation_content_changed(project, (slide_id,))
        resolve_impacts(run_dir, affected=("annotation geometry", "annotation timing"), slide_ids=(slide_id,), snapshot=impact)
        settings = self._store.read_settings(run_dir) or default_annotation_settings()
        return {"slide_id": slide_id, "revision": page.revision,
                "confirmed": sum(i.status.content == "confirmed" for i in page.items),
                "timeline_built": True, "timeline_changed": changed, "build_id": compiled.get("build_id"),
                "readiness": self._readiness(settings, run_dir, self._slide_ids_or_404(project), canvas)}

    def annotation_editor_ink(self, db, project_id, slide_id, annotation_id, stroke_index, revision):
        from io import BytesIO
        from annotation_build import ink_request
        from annotation_ink import render_stroke_rgba
        project = self._project_or_404(db, project_id)
        if slide_id not in self._slide_ids_or_404(project):
            raise HTTPException(status_code=404, detail="Slide 不存在")
        canvas = self._canvas_for(project)
        with self._lock_for(project):
            run_dir = self._run_dir(project)
            page = self._store.read_page(run_dir, slide_id, canvas=canvas)
            if not page or page.revision != revision:
                raise HTTPException(status_code=409, detail="勾画已更新，请刷新画面")
            item = next((item for item in page.items if item.annotation_id == annotation_id), None)
            if item is None:
                raise HTTPException(status_code=404, detail="勾画不存在")
            payload = self._items_with_strokes(run_dir, slide_id, [item])[0]
            if not 0 <= stroke_index < len(payload["strokes"]):
                raise HTTPException(status_code=404, detail="笔迹不存在")
            request = ink_request(item, payload["strokes"][stroke_index], canvas, stroke_index)
        output = BytesIO()
        render_stroke_rgba(request, arc=1.0).save(output, format="PNG")
        return output.getvalue()

    def annotation_asset(self, db, project_id, slide_id, build_id, annotation_id, stroke_index, frame_index):
        from annotation_build import read_json
        project = self._project_or_404(db, project_id)
        if slide_id not in self._slide_ids_or_404(project):
            raise HTTPException(status_code=404, detail="Slide 不存在")
        directory = self._slide_file(project, slide_id, "annotations.json").parent
        for filename in ("annotation_preview.json", "annotation_timeline.json"):
            manifest = read_json(directory / filename, optional=True)
            if not manifest or manifest.get("build_id") != build_id:
                continue
            event = next((e for e in manifest.get("events", []) if e["annotation_id"] == annotation_id), None)
            if event and 0 <= stroke_index < len(event["strokes"]):
                ink = event["strokes"][stroke_index].get("ink", {})
                if 0 <= frame_index < int(ink.get("frame_count", 0)):
                    path = directory / "annotation_ink" / annotation_id / ink["dir"] / f"frame_{frame_index:03d}.png"
                    if path.is_file() and path.resolve().is_relative_to(directory.resolve()):
                        return path
        raise HTTPException(status_code=404, detail="勾画帧不存在或预览已更新")

    def preview_scene_asset(self, db, project_id, slide_id, asset):
        from annotation_build import read_json
        project = self._project_or_404(db, project_id)
        if slide_id not in self._slide_ids_or_404(project):
            raise HTTPException(status_code=404, detail="Slide 不存在")
        directory = self._slide_file(project, slide_id, "annotations.json").parent
        scene = read_json(directory / "scene.json", optional=True) or {}
        allowed = {"visual_draft.png"}
        allowed.update(layer.get("asset") for layer in scene.get("layers", []))
        allowed.add(scene.get("canvas", {}).get("background_asset"))
        path = directory / asset
        if asset not in allowed or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise HTTPException(status_code=404, detail="预览图片不存在")
        return path

    def _op_restore(
        self,
        operation: Dict[str, Any],
        items: List[AnnotationItem],
        beats: Dict[str, Dict[str, Any]],
        image_hash: Optional[str],
        narration_hash: Optional[str],
        issues: List[Issue],
        *,
        path: str,
        canvas: Tuple[int, int],
    ) -> None:
        from annotation_contracts import AnnotationInputs, AnnotationProtection, AnnotationStatus

        if operation.get("source") != "ai":
            issues.append(Issue(f"{path}.source", "bad_enum", "restore 仅支持 source=ai"))
            return
        snapshot_items = (operation.get("items") or []) if isinstance(operation.get("items"), list) else None
        if snapshot_items is None:
            issues.append(Issue(f"{path}.items", "required", "restore 需要携带要恢复的建议条目"))
            return
        for snapshot_index, raw in enumerate(snapshot_items):
            draft = AnnotationItem.from_payload(
                raw, issues, canvas=canvas, path=f"{path}.items[{snapshot_index}]", require_id=False
            )
            if draft is None:
                continue
            anchor = None
            if draft.anchor is not None:
                anchor = self._validate_anchor(draft.anchor.to_dict(), beats, issues, path=f"{path}.items[{snapshot_index}].anchor")
            items.append(
                AnnotationItem(
                    annotation_id=next_annotation_id([i.annotation_id for i in items]),
                    target=draft.target,
                    anchor=anchor,
                    style=draft.style,
                    timing=draft.timing,
                    status=AnnotationStatus(content="draft", spatial="needs_review", temporal="awaiting_audio"),
                    protection=AnnotationProtection(source="ai", modified_fields=(), locked=False),
                    inputs=AnnotationInputs(image_hash=image_hash, narration_hash=narration_hash, audio_hash=None),
                )
            )

    # ------------------------------------------------------------ W3: 文字布局

    def get_text_layout(self, db: Session, project_id: str, slide_id: str) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        slide_ids = self._slide_ids_or_404(project)
        if slide_id not in slide_ids:
            raise HTTPException(status_code=404, detail="Slide 不存在")
        if self._layout_builder is None:
            raise HTTPException(status_code=503, detail="文字识别引擎尚未配置")
        run_dir = self._run_dir(project)
        try:
            layout = self._layout_builder.load(run_dir, slide_id)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if layout is None:
            return {"slide_id": slide_id, "layout": None}
        from annotation_text_layout import candidate_tokens

        return {
            "slide_id": slide_id,
            "layout_revision": layout.get("layout_revision"),
            "image_hash": layout.get("image_hash"),
            "engine": layout.get("engine"),
            "candidates": candidate_tokens(layout),
            "lines": layout.get("lines", []),
            "corrections": layout.get("corrections") or {},
        }

    def patch_text_layout(self, db: Session, project_id: str, slide_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        slide_ids = self._slide_ids_or_404(project)
        if slide_id not in slide_ids:
            raise HTTPException(status_code=404, detail="Slide 不存在")
        if self._layout_builder is None:
            raise HTTPException(status_code=503, detail="文字识别引擎尚未配置")
        expected_layout_revision = payload.get("expected_layout_revision")
        if not isinstance(expected_layout_revision, int) or isinstance(expected_layout_revision, bool):
            raise HTTPException(status_code=422, detail="expected_layout_revision 必须是整数")
        corrections = payload.get("corrections")
        if not isinstance(corrections, dict) or not corrections:
            raise HTTPException(status_code=422, detail="corrections 必须是非空对象 {token_id: text}")

        run_dir = self._run_dir(project)
        with self._lock_for(project):
            try:
                layout = self._layout_builder.load(run_dir, slide_id)
            except ValueError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            if layout is None:
                raise HTTPException(status_code=422, detail="请先运行文字识别(detect_text)")
            if int(layout.get("layout_revision") or 0) != expected_layout_revision:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "layout_revision_conflict", "current_layout_revision": layout.get("layout_revision")},
                )
            changed = False
            for token_id, text in corrections.items():
                if not isinstance(text, str):
                    raise HTTPException(status_code=422, detail=f"token {token_id} 的纠正文本必须是字符串")
                if len(text) > 200:
                    raise HTTPException(status_code=413, detail="纠正文本过长")
                try:
                    layout, updated = self._layout_builder.apply_correction(layout, str(token_id), text)
                except KeyError:
                    raise HTTPException(status_code=422, detail=f"未知候选 token_id: {token_id}") from None
                changed = changed or updated
            if changed:
                self._layout_builder.save(run_dir, slide_id, layout)
        from annotation_text_layout import candidate_tokens

        return {
            "slide_id": slide_id,
            "layout_revision": layout.get("layout_revision"),
            "corrections": layout.get("corrections") or {},
            "candidates": candidate_tokens(layout),
        }

    # ------------------------------------------------------------ W3: 任务

    def submit_job(self, db: Session, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        operation = payload.get("operation")
        if operation not in ("detect_text", "plan", "align", "preview"):
            raise HTTPException(status_code=422, detail="operation 仅支持 detect_text / plan / align / preview")
        if self._job_manager is None or self._layout_builder is None:
            raise HTTPException(status_code=503, detail="勾画任务引擎尚未配置")
        if operation == "detect_text" and not self._ocr_ready():
            raise HTTPException(status_code=503, detail="OCR 引擎未配置 API Key,请在设置中填写后重试")
        if operation == "plan" and getattr(self._job_manager, "_deps", None) is not None and self._job_manager._deps.planner is None:
            raise HTTPException(status_code=503, detail="AI 规划依赖未配置")
        slide_ids = self._slide_ids_or_404(project)
        requested = payload.get("slide_ids") or slide_ids
        if not isinstance(requested, list) or not requested:
            raise HTTPException(status_code=422, detail="slide_ids 必须是非空数组")
        if len(requested) > 40:
            raise HTTPException(status_code=413, detail="单次任务页数超过上限 40")
        requested = [str(sid) for sid in requested]
        for slide_id in requested:
            if slide_id not in slide_ids:
                raise HTTPException(status_code=404, detail=f"Slide {slide_id} 不存在")
        request_key = payload.get("request_key")
        if operation == "preview":
            if len(requested) != 1:
                raise HTTPException(status_code=422, detail="预览任务只支持单页")
            expected = payload.get("expected_revision")
            if not isinstance(expected, int) or isinstance(expected, bool):
                raise HTTPException(status_code=422, detail="expected_revision 必须是整数")
            job, _created = self._job_manager.submit_preview(project.id, requested[0],
                {"expected_revision": expected}, self.prepare_slide, request_key=request_key)
        elif operation == "detect_text":
            run_dir = self._run_dir(project)
            canvas = self._canvas_for(project)
            from project_storage import slide_file

            targets: List[Tuple[str, str, Tuple[int, int], bytes]] = []
            for slide_id in requested:
                image_path = Path(slide_file(run_dir, str(slide_id), VISUAL_DRAFT_FILE))
                try:
                    image_bytes = image_path.read_bytes()
                except OSError as exc:
                    raise HTTPException(status_code=422, detail=f"页面 {slide_id} 缺少图片,请先在第三步生成") from exc
                targets.append(
                    (str(slide_id), hashlib.sha256(image_bytes).hexdigest(), canvas, image_bytes)
                )
            job, _created = self._job_manager.submit_detect(
                project.id,
                targets,
                request_key=request_key,
            )
        else:
            job, _created = self._job_manager.submit_plan(
                project.id,
                requested,
                request_key=request_key,
                operation=operation,
            )
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "error_detail": payload.get("error_detail"),
            "status": job.status,
        }

    # ------------------------------------------------------------ W3: Prompt 编辑

    def get_prompts(self, db: Session, project_id: str, slide_id: Optional[str] = None) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        if self._prompt_store is None:
            raise HTTPException(status_code=503, detail="勾画 Prompt 模块尚未配置")
        run_dir = self._run_dir(project)
        system_prompt, source = self._prompt_store.effective_system_prompt(run_dir)
        overrides = self._prompt_store.load_overrides(run_dir)
        payload_path = self._prompt_store.prompts_path_for(run_dir)
        current = None
        if isinstance(payload_path, (str, Path)) or payload_path is not None:
            current = self._prompt_store.read_json_file(payload_path)
        revision = int(current.get("revision") or 0) if isinstance(current, dict) else 0
        response: Dict[str, Any] = {
            "builtin_version": self._prompt_store_version(),
            "source": source,
            "revision": revision,
            "builtin_system_prompt": BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT,
            "override_system_prompt": overrides.get("plan_system_prompt"),
            "system_prompt": system_prompt,
        }
        # 完整输入预览:基于当前页真实快照(不含凭据)
        if slide_id:
            slide_ids = self._slide_ids_or_404(project)
            if slide_id not in slide_ids:
                raise HTTPException(status_code=404, detail="Slide 不存在")
            preview = self._prompt_preview(project, run_dir, slide_id, system_prompt)
            response["preview"] = preview
        return response

    def _prompt_store_version(self) -> str:
        from annotation_prompt_templates import ANNOTATION_PLAN_PROMPT_VERSION  # noqa: F811

        return ANNOTATION_PLAN_PROMPT_VERSION

    def _prompt_preview(self, project: Project, run_dir: str, slide_id: str, system_prompt: str) -> Dict[str, Any]:
        from annotation_prompt_templates import compose_plan_prompts
        from annotation_text_layout import candidate_tokens

        layout = self._layout_builder.load(run_dir, slide_id) if self._layout_builder else None
        candidates = candidate_tokens(layout) if layout else []
        # 与真实 plan 任务(annotation_jobs)一致:语块 id 映射为 beat_id,
        # 否则预览 user payload 里 beat_id 恒为 null。
        beats = [
            {"beat_id": beat.get("id"), "spoken_text": beat.get("spoken_text")}
            for beat in self._read_beats(project, slide_id)
            if isinstance(beat, dict)
        ]
        canvas = self._canvas_for(project)
        try:
            page = self._store.read_page(run_dir, slide_id, canvas=canvas)
        except AnnotationStoreError:
            page = None
        protected = []
        for item in page.items if page else ():
            if item.protection.source == "manual" or item.protection.locked or item.protection.modified_fields:
                protected.append({
                    "quote": item.anchor.quote if item.anchor else (item.target.quote or ""),
                    "beat_id": item.anchor.beat_id if item.anchor else None,
                    "style": item.style.type,
                    "locked": item.protection.locked,
                    "source": item.protection.source,
                    "target_kind": item.target.kind,
                    "target_candidate_ids": list(item.target.token_ids),
                })
        settings = self._store.read_settings(run_dir) or default_annotation_settings()
        emphasis = settings.defaults.get("emphasis", "moderate")
        if emphasis not in EMPHASIS_LEVELS:
            emphasis = "moderate"
        prompts = compose_plan_prompts(
            system_prompt=system_prompt,
            beats=beats,
            candidates=candidates,
            protected_items=protected,
            emphasis=emphasis,
        )
        return {
            "slide_id": slide_id,
            "user_payload": json.loads(prompts["user"]),
            "candidate_count": len(candidates),
            "beat_count": len(beats),
            "note": "预览不含 API 密钥;实际请求还会附带当前项目的模型配置。",
        }

    def put_prompts(self, db: Session, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        if self._prompt_store is None:
            raise HTTPException(status_code=503, detail="勾画 Prompt 模块尚未配置")
        run_dir = self._run_dir(project)
        action = payload.get("action", "save")
        if action == "reset_default":
            updated = self._prompt_store.reset_override(run_dir, now_iso=self._now_iso())
        else:
            updated = self._prompt_store.save_override(
                run_dir,
                payload.get("system_prompt"),
                expected_revision=payload.get("expected_revision"),
                now_iso=self._now_iso(),
            )
        return {"revision": updated["revision"], "builtin_version": updated["builtin_version"]}

    def get_job(self, db: Session, project_id: str, job_id: str) -> Dict[str, Any]:
        project = self._project_or_404(db, project_id)
        if self._job_manager is None:
            raise HTTPException(status_code=503, detail="勾画任务引擎尚未配置")
        job = self._deps_job_or_404(project_id, job_id)
        payload = job.get_payload()
        if job.job_type == "annotation_preview" and job.status == "succeeded" and not payload.get("export"):
            from annotation_build import input_snapshot
            sid = payload.get("slide_id")
            canvas = self._canvas_for(project)
            page = self._store.read_page(self._run_dir(project), sid, canvas=canvas)
            result = payload.get("result") or {}
            directory = self._slide_file(project, sid, "annotations.json").parent
            if (not page or page.revision != result.get("revision")
                    or any(result.get("timeline", {}).get("inputs", {}).get(key) != value
                           for key, value in input_snapshot(directory, page.items, canvas).items())):
                raise HTTPException(status_code=409, detail={"code": "stale_preview"})
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "error_detail": payload.get("error_detail"),
            "error": job.error,
            "retryable": bool(payload.get("retryable")),
            "result": payload.get("result"),
            "created_at": str(job.created_at or ""),
            "finished_at": str(job.finished_at or ""),
        }

    def cancel_job(self, db: Session, project_id: str, job_id: str) -> Dict[str, Any]:
        self._project_or_404(db, project_id)
        if self._job_manager is None:
            raise HTTPException(status_code=503, detail="勾画任务引擎尚未配置")
        self._deps_job_or_404(project_id, job_id)
        cancelled = self._job_manager.cancel(job_id)
        return {"job_id": job_id, "cancelled": bool(cancelled)}

    def _deps_job_or_404(self, project_id: str, job_id: str):
        job = self._job_manager.get_job(job_id)
        if job is None or job.project_id != project_id or not str(job.job_type).startswith("annotation_"):
            raise HTTPException(status_code=404, detail="任务不存在")
        return job


class _ItemWithStrokesView:
    """时间轴构建器用的只读包装:附加 strokes 字段。"""

    def __init__(self, item, strokes):
        self._item = item
        self.strokes = tuple(strokes)

    def __getattr__(self, name):
        return getattr(self._item, name)


_SERVICE: Optional[AnnotationService] = None


def configure_annotation_service(dependencies: AnnotationServiceDependencies) -> None:
    global _SERVICE
    _SERVICE = AnnotationService(dependencies)


def get_annotation_service() -> AnnotationService:
    if _SERVICE is None:
        raise RuntimeError("annotation service 尚未配置依赖(启动装配缺失)")
    return _SERVICE
