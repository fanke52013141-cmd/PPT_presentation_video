# -*- coding: utf-8 -*-
"""勾画标注模块的有界任务执行(W3:detect_text;plan/align 随 W3/W4 落地)。

- 并发有界:进程内信号量限制同时执行的任务数;任务线程不持有 HTTP 请求
  对象或数据库会话(会话按需短开短关)。
- 取消:取消标志由执行线程在阶段间检查;取消后结果不发布。
- 输入版本:执行前读取输入快照,发布前复核图像/讲稿哈希;变化则丢弃
  结果并标记 stale_input,不覆盖正式数据。
- 服务端从不静默吞错:失败写入 job.error(脱敏)。
"""
from __future__ import annotations
from annotation_contracts import EMPHASIS_LEVELS

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from account_context import (
    DEFAULT_ACCOUNT_ID,
    get_current_account_id,
    reset_current_account_id,
    set_current_account_id,
)
from annotation_contracts import AnnotationItem, AnnotationPage, next_annotation_id

logger = logging.getLogger("PPTStudio.AnnotationJobs")


def _next_id(items: List[AnnotationItem]) -> str:
    return next_annotation_id([item.annotation_id for item in items])


def _with_id(item: AnnotationItem, annotation_id: str) -> AnnotationItem:
    return replace(item, annotation_id=annotation_id)


def _page_with(*, revision: int, slide_id: str, items: List[AnnotationItem], snapshot: Optional[Dict[str, Any]], now: str) -> AnnotationPage:
    return AnnotationPage(slide_id=slide_id, revision=revision, items=tuple(items), ai_suggestion_snapshot=snapshot, updated_at=now)

_MAX_CONCURRENT_JOBS = 2
_JOB_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT_JOBS)
_OCR_RETRY_DELAYS = (1.0, 2.0)


@dataclass(frozen=True)
class AnnotationJobDependencies:
    job_store: Any  # AnnotationJobStore
    session_factory: Callable[[], Any]
    text_layout_builder: Any  # TextLayoutBuilder
    recognize: Callable[[bytes, Any], Any]  # (image_bytes, config) -> BaiduOcrResult
    now_iso: Callable[[], str] = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # plan 任务依赖:annotation store(页面读写)、planner、项目锁工厂、画布
    annotation_store: Any = None
    planner: Any = None
    align_audio: Any = None
    lock_for: Callable[[Any], Any] = lambda project: _null_lock()
    canvas: Tuple[int, int] = (1920, 1080)


class _null_lock:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class AnnotationJobManager:
    """annotation_* 任务的提交、执行与查询编排。"""

    def __init__(self, dependencies: AnnotationJobDependencies):
        self._deps = dependencies
        self._executor = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_JOBS, thread_name_prefix="annotation-job")
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _canvas_for(self, project: Any) -> Tuple[int, int]:
        profile_id = getattr(project, "canvas_profile", None)
        if not profile_id:
            return tuple(self._deps.canvas)
        from canvas_profile_service import get_project_canvas

        canvas = get_project_canvas(project)
        return int(canvas["width"]), int(canvas["height"])

    # ------------------------------------------------------------ 提交

    def submit_preview(self, project_id, slide_id, payload, prepare, *, request_key=None):
        account_id = get_current_account_id()
        with self._lock:
            job = self._deps.job_store.create(project_id, job_type="annotation_preview",
                payload={"account_id": account_id, "slide_id": slide_id,
                         "expected_revision": payload.get("expected_revision")}, request_key=request_key)
            created = job.status == "queued" and job.id not in self._cancel_flags
            if created:
                event = threading.Event()
                self._cancel_flags[job.id] = event
        if created:
            def run():
                with _JOB_SEMAPHORE:
                    token = set_current_account_id(account_id)
                    try:
                        if event.is_set():
                            self._deps.job_store.mark_cancelled(job.id)
                            return
                        self._deps.job_store.mark_running(job.id, "prepare")
                        with self._deps.session_factory() as db:
                            result = prepare(db, project_id, slide_id, payload, cancel_event=event,
                                progress=lambda value, stage: self._deps.job_store.update_progress(job.id, value, stage=stage))
                        if event.is_set():
                            self._deps.job_store.mark_cancelled(job.id)
                        else:
                            self._deps.job_store.mark_succeeded(job.id, "done", result)
                    except Exception as exc:
                        if event.is_set():
                            self._deps.job_store.mark_cancelled(job.id)
                        else:
                            detail = getattr(exc, "detail", None)
                            self._deps.job_store.mark_failed(job.id, str(detail or exc), detail=detail)
                    finally:
                        reset_current_account_id(token)
                        with self._lock:
                            self._cancel_flags.pop(job.id, None)
            self._executor.submit(run)
        return job, created

    def submit_detect(
        self,
        project_id: str,
        slide_targets: List[Tuple[str, str, Tuple[int, int], bytes]],
        *,
        request_key: Optional[str] = None,
    ) -> Tuple[Any, bool]:
        """提交 detect_text 任务;slide_targets = [(slide_id, image_hash, size, bytes)]。

        返回 (job, created);request_key 命中既有活跃/成功任务时复用。
        """
        account_id = get_current_account_id()
        with self._lock:
            job = self._deps.job_store.create(
                project_id, job_type="annotation_detect",
                payload={"account_id": account_id, "slides": [{"slide_id": sid, "image_hash": h} for sid, h, _, _ in slide_targets]},
                request_key=request_key)
            created = job.status == "queued" and job.id not in self._cancel_flags
            if created:
                self._cancel_flags[job.id] = threading.Event()
        if created:
            self._spawn(job.id, project_id, slide_targets, account_id)
        return job, created

    def _resolve_worker_account(self, project_id: str, account_id: Optional[str]) -> str:
        """历史任务 payload 缺账号时回退项目行归属,绝不无条件默认 default。"""
        if account_id:
            return account_id
        try:
            project = self._project(project_id)
            return str(getattr(project, "account_id", "") or DEFAULT_ACCOUNT_ID)
        except Exception:
            return DEFAULT_ACCOUNT_ID

    def _spawn(
        self,
        job_id: str,
        project_id: str,
        slide_targets: List[Tuple[str, str, Tuple[int, int], bytes]],
        account_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            cancel_event = self._cancel_flags.setdefault(job_id, threading.Event())

        def run() -> None:
            _JOB_SEMAPHORE.acquire()
            token = set_current_account_id(self._resolve_worker_account(project_id, account_id))
            try:
                self._run_detect(job_id, project_id, slide_targets, cancel_event)
            except Exception as exc:  # 兜底:任何未捕获错误都必须落到持久状态
                logger.exception("annotation job %s crashed", job_id)
                try:
                    self._deps.job_store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
                except Exception:
                    logger.exception("failed to persist crash state for %s", job_id)
            finally:
                reset_current_account_id(token)
                _JOB_SEMAPHORE.release()
                with self._lock:
                    self._cancel_flags.pop(job_id, None)

        self._executor.submit(run)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_flags.get(job_id)
        if event is not None:
            event.set()
            return True
        # 任务不在执行中:若尚未完成,直接标取消(幂等)
        job = self._deps.job_store.get(job_id)
        if job is not None and job.status in ("queued",):
            self._deps.job_store.mark_cancelled(job_id)
            return True
        return False

    def get_job(self, job_id: str):
        return self._deps.job_store.get(job_id)

    # ------------------------------------------------------------ detect_text

    def _recognize_with_retry(self, job_id, cancel_event, image_bytes, config):
        from annotation_ocr_baidu import BaiduOcrError

        for attempt in range(len(_OCR_RETRY_DELAYS) + 1):
            if cancel_event.is_set():
                raise ValueError("cancelled")
            try:
                return self._deps.recognize(image_bytes, config)
            except BaiduOcrError as exc:
                if not exc.retryable or attempt == len(_OCR_RETRY_DELAYS):
                    raise
                self._deps.job_store.update_progress(job_id, 5, stage="ocr_retry")
                if cancel_event.wait(_OCR_RETRY_DELAYS[attempt]):
                    raise ValueError("cancelled") from exc

    def _run_detect(
        self,
        job_id: str,
        project_id: str,
        slide_targets: List[Tuple[str, str, Tuple[int, int], bytes]],
        cancel_event: threading.Event,
    ) -> None:
        store = self._deps.job_store
        store.mark_running(job_id, "detect")
        results: List[Dict[str, Any]] = []
        total = len(slide_targets)
        for index, (slide_id, expected_hash, image_size, image_bytes) in enumerate(slide_targets):
            if cancel_event.is_set():
                store.mark_cancelled(job_id)
                return
            actual_hash = hashlib.sha256(image_bytes).hexdigest()
            if actual_hash != expected_hash:
                # 提交到执行之间图片被替换:该页跳过并标记 stale
                results.append({"slide_id": slide_id, "status": "stale_input"})
                continue
            try:
                run_dir = self._run_dir(project_id)
                def publish_layout(payload, previous):
                    with self._deps.lock_for(self._project(project_id)):
                        if cancel_event.is_set():
                            raise ValueError("cancelled")
                        current = self._read_image(run_dir, slide_id)
                        if current is None or hashlib.sha256(current).hexdigest() != expected_hash:
                            raise ValueError("stale_input")
                        try:
                            latest = self._deps.text_layout_builder.load(run_dir, slide_id)
                        except ValueError:
                            latest = None
                        if latest != previous:
                            raise ValueError("layout_changed")
                        self._deps.text_layout_builder.save(run_dir, slide_id, payload)
                layout, detected = self._deps.text_layout_builder.get_or_detect(
                    run_dir,
                    slide_id,
                    image_bytes,
                    actual_hash,
                    image_size,
                    recognize=lambda image, config: self._recognize_with_retry(job_id, cancel_event, image, config),
                    publish=publish_layout,
                )
                results.append(
                    {
                        "slide_id": slide_id,
                        "status": "detected" if detected else "cached",
                        "layout_revision": layout.get("layout_revision"),
                        "granularity": layout.get("engine", {}).get("granularity"),
                    }
                )
            except Exception as exc:
                # 单页失败不拖垮整批;错误文本先脱敏再落库
                from annotation_job_store import _sanitize_error

                status = "stale_input" if str(exc) in ("stale_input", "layout_changed") else "failed"
                results.append({"slide_id": slide_id, "status": status, "error": _sanitize_error(str(exc))[:300]})
            store.update_progress(job_id, 10 + int(80 * (index + 1) / max(1, total)), stage="detect")
        if cancel_event.is_set():
            store.mark_cancelled(job_id)
            return
        failed = [result for result in results if result.get("status") == "failed"]
        if failed and len(failed) == len(results):
            # 全部页面失败:任务按失败收场,不得向用户谎报"识别完成"
            store.mark_failed(job_id, str(failed[0].get("error") or "detect failed"))
            return
        store.mark_succeeded(job_id, "done", {"slides": results})

    # ------------------------------------------------------------ plan

    def submit_plan(self, project_id: str, slide_ids: List[str], *, request_key: Optional[str] = None, operation="plan") -> Tuple[Any, bool]:
        account_id = get_current_account_id()
        with self._lock:
            job = self._deps.job_store.create(
                project_id, job_type="annotation_" + operation,
                payload={"account_id": account_id, "slides": [{"slide_id": sid} for sid in slide_ids]},
                request_key=request_key)
            created = job.status == "queued" and job.id not in self._cancel_flags
            if created:
                cancel_event = threading.Event()
                self._cancel_flags[job.id] = cancel_event
        if created:
            def run() -> None:
                _JOB_SEMAPHORE.acquire()
                token = set_current_account_id(self._resolve_worker_account(project_id, account_id))
                try:
                    (self._run_alignment if operation == "align" else self._run_plan)(job.id, project_id, slide_ids, cancel_event)
                except Exception as exc:
                    logger.exception("annotation plan job %s crashed", job.id)
                    try:
                        self._deps.job_store.mark_failed(job.id, f"{type(exc).__name__}: {exc}")
                    except Exception:
                        logger.exception("failed to persist crash state for %s", job.id)
                finally:
                    reset_current_account_id(token)
                    _JOB_SEMAPHORE.release()
                    with self._lock:
                        self._cancel_flags.pop(job.id, None)

            self._executor.submit(run)
        return job, created

    def _run_alignment(self, job_id, project_id, slide_ids, cancel_event):
        from annotation_build import file_hash
        from pipeline_lifecycle import write_json_atomic
        from project_storage import slide_dir
        store = self._deps.job_store
        store.mark_running(job_id, "align")
        if self._deps.align_audio is None:
            raise RuntimeError("音频定位引擎未配置")
        run_dir = self._run_dir(project_id)
        results = []
        changed_slides = []
        for index, slide_id in enumerate(slide_ids):
            if cancel_event.is_set():
                store.mark_cancelled(job_id)
                return
            project = self._project(project_id)
            directory = Path(slide_dir(run_dir, slide_id))
            with self._deps.lock_for(project):
                hashes = {name: file_hash(directory / name) for name in ("voice.mp3", "narration_beats.json")}
                beats = self._read_beats(run_dir, slide_id)
            result = self._deps.align_audio(directory, beats, cancel_event)
            if cancel_event.is_set() or result is None:
                store.mark_cancelled(job_id)
                return
            with self._deps.lock_for(project):
                if any(file_hash(directory / name) != value for name, value in hashes.items()):
                    raise RuntimeError("stale_input: 音频或讲稿已修改，请重新定位")
                from annotation_build import read_json
                previous = read_json(directory / "word_alignment.json", optional=True)
                if previous != result:
                    write_json_atomic(directory / "word_alignment.json", result)
                    changed_slides.append(slide_id)
            results.append({"slide_id": slide_id, "status": "aligned", "tokens": len(result.get("tokens", []))})
            store.update_progress(job_id, int(95 * (index + 1) / len(slide_ids)), stage="align")
        if changed_slides:
            from database import Project
            from invalidation_service import annotation_content_changed
            db = self._deps.session_factory()
            try:
                project = db.query(Project).filter(Project.id == project_id).first()
                annotation_content_changed(project, changed_slides)
                db.commit()
            finally:
                db.close()
        store.mark_succeeded(job_id, "done", {"slides": results})

    def _run_plan(self, job_id: str, project_id: str, slide_ids: List[str], cancel_event: threading.Event) -> None:
        store = self._deps.job_store
        annotation_store = self._deps.annotation_store
        planner = self._deps.planner
        if annotation_store is None or planner is None:
            store.mark_failed(job_id, "planner dependencies not configured")
            return
        store.mark_running(job_id, "plan")
        run_dir = self._run_dir(project_id)

        results: List[Dict[str, Any]] = []
        total = len(slide_ids)
        for index, slide_id in enumerate(slide_ids):
            if cancel_event.is_set():
                store.mark_cancelled(job_id)
                return
            # ---- 短锁 1:读取输入快照(页面 revision、图像/讲稿哈希) ----
            project = self._project(project_id)
            canvas = self._canvas_for(project)
            with self._deps.lock_for(project):
                page = annotation_store.read_page(run_dir, slide_id, canvas=canvas)
                page_revision = page.revision if page else 0
                image_bytes = self._read_image(run_dir, slide_id)
                image_hash = hashlib.sha256(image_bytes).hexdigest() if image_bytes else None
                narration_hash = self._file_hash(run_dir, slide_id, "narration_beats.json")
                layout = self._deps.text_layout_builder.load(run_dir, slide_id)
            if image_hash is None or narration_hash is None:
                results.append({"slide_id": slide_id, "status": "skipped", "reason": "missing_inputs"})
                continue
            if layout is None:
                results.append({"slide_id": slide_id, "status": "skipped", "reason": "no_text_layout"})
                continue
            beats = [
                {"beat_id": str(b.get("id")), "spoken_text": str(b.get("spoken_text") or "")}
                for b in self._read_beats(run_dir, slide_id)
            ]
            from annotation_text_layout import candidate_tokens

            settings = annotation_store.read_settings(run_dir)
            configured_emphasis = settings.defaults.get("emphasis") if settings else None
            emphasis = configured_emphasis if configured_emphasis in EMPHASIS_LEVELS else "moderate"
            try:
                items, snapshot, issues = planner.plan_slide(
                    run_dir,
                    slide_id,
                    beats,
                    candidate_tokens(layout),
                    page,
                    emphasis=emphasis,
                    image_hash=image_hash,
                    narration_hash=narration_hash,
                    now_iso=self._deps.now_iso(),
                )
            except Exception as exc:
                from annotation_job_store import _sanitize_error

                results.append({"slide_id": slide_id, "status": "failed", "error": _sanitize_error(str(exc))[:300]})
                store.update_progress(job_id, 10 + int(80 * (index + 1) / max(1, total)), stage="plan")
                continue

            # ---- 短锁 2:发布前复核输入版本与页面 revision ----
            with self._deps.lock_for(project):
                if cancel_event.is_set():
                    store.mark_cancelled(job_id)
                    return
                current_page = annotation_store.read_page(run_dir, slide_id, canvas=canvas)
                current_revision = current_page.revision if current_page else 0
                current_image = self._read_image(run_dir, slide_id)
                current_image_hash = hashlib.sha256(current_image).hexdigest() if current_image else None
                if (
                    current_revision != page_revision
                    or current_image_hash != image_hash
                    or self._file_hash(run_dir, slide_id, "narration_beats.json") != narration_hash
                ):
                    results.append({"slide_id": slide_id, "status": "stale_input"})
                    continue
                merged = list(current_page.items) if current_page else []
                assigned = []
                for item in items:
                    assigned.append(
                        _with_id(item, _next_id(merged))
                    )
                    merged.append(assigned[-1])
                if assigned:
                    updated_page = _page_with(revision=page_revision + 1, slide_id=slide_id, items=merged, snapshot=snapshot, now=self._deps.now_iso())
                    annotation_store.write_page(run_dir, slide_id, updated_page)
            results.append(
                {
                    "slide_id": slide_id,
                    "status": "planned",
                    "added": len(assigned),
                    "review_issues": [issue.code for issue in issues],
                }
            )
            store.update_progress(job_id, 10 + int(80 * (index + 1) / max(1, total)), stage="plan")
        if cancel_event.is_set():
            store.mark_cancelled(job_id)
            return
        failed = [result for result in results if result.get("status") == "failed"]
        if failed and len(failed) == len(results):
            # 全部页面失败:任务按失败收场,不得向用户谎报"AI 重点已生成"
            store.mark_failed(job_id, str(failed[0].get("error") or "plan failed"))
            return
        store.mark_succeeded(job_id, "done", {"slides": results})

    def _project(self, project_id: str):
        from database import Project

        db = self._deps.session_factory()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project is None:
                raise ValueError(f"project {project_id} not found")
            return project
        finally:
            db.close()

    def _read_image(self, run_dir: str, slide_id: str) -> Optional[bytes]:
        from project_storage import slide_file

        try:
            return Path(slide_file(run_dir, slide_id, "visual_draft.png")).read_bytes()
        except OSError:
            return None

    def _file_hash(self, run_dir: str, slide_id: str, filename: str) -> Optional[str]:
        from project_storage import slide_file

        try:
            return hashlib.sha256(Path(slide_file(run_dir, slide_id, filename)).read_bytes()).hexdigest()
        except OSError:
            return None

    def _read_beats(self, run_dir: str, slide_id: str) -> List[Dict[str, Any]]:
        import json

        from project_storage import slide_file

        try:
            payload = json.loads(Path(slide_file(run_dir, slide_id, "narration_beats.json")).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        beats = payload.get("beats") if isinstance(payload, dict) else None
        return [b for b in beats if isinstance(b, dict) and b.get("id")] if isinstance(beats, list) else []

    def _run_dir(self, project_id: str) -> str:
        return str(self._project(project_id).run_dir)
