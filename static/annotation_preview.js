// Formal audio + Reveal + ink preview. Uses the exact Remotion video component.
const ANNOTATION_PREVIEW = { prepared: null, loading: null, generation: 0 };

function annotationVideoAudioTime(frame, fps, audioTimeline, slideDuration) {
  const pageTime = frame / fps;
  const delay = Number(audioTimeline.audio_start_sec || 0);
  const contentDuration = Number(audioTimeline.audio_content_duration_sec);
  const end = Number.isFinite(contentDuration) && contentDuration > 0 ? Math.min(slideDuration, delay + contentDuration) : Math.min(slideDuration, Number(audioTimeline.duration_sec) || slideDuration);
  return fps > 0 && Number.isFinite(pageTime) && pageTime >= delay && pageTime < end ? pageTime - delay : null;
}

async function waitAnnotationPreviewJob(projectId, slideId, revision, { deadlineMs = 360000 } = {}) {
  const key = `annotation-preview:${projectId}:${slideId}`;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_) { saved = null; }
  if (!saved || saved.revision !== revision) {
    const job = await API.post(`${annotationsApiBase(projectId)}/jobs`, {
      operation: 'preview', slide_ids: [slideId], expected_revision: revision,
      request_key: `preview-${slideId}-${revision}-${Date.now()}`,
    }, {silent: true});
    saved = {jobId: job.job_id, revision};
    sessionStorage.setItem(key, JSON.stringify(saved));
  }
  const deadline = Date.now() + deadlineMs;
  for (;;) {
    let job;
    try {
      job = await API.get(`${annotationsApiBase(projectId)}/jobs/${encodeURIComponent(saved.jobId)}`, {silent: true});
    } catch (error) {
      if ([404, 409].includes(error.status)) sessionStorage.removeItem(key);
      throw error;
    }
    if (ANNOTATIONS_WS.projectId !== projectId || ANNOTATIONS_WS.page.slide_id !== slideId) {
      throw new Error('已切换页面，预览任务继续执行；回到原页可恢复查看。');
    }
    if (job.status === 'succeeded') {
      sessionStorage.removeItem(key);
      return job.result;
    }
    if (!['queued', 'running'].includes(job.status)) {
      sessionStorage.removeItem(key);
      const error = new Error(job.error || `预览任务${job.status}，可重新生成。`);
      error.body = {detail: job.error_detail};
      throw error;
    }
    if (Date.now() > deadline) {
      sessionStorage.removeItem(key);
      throw new Error('预览准备超时（超过 6 分钟），请重试或先检查本页音频与图片。');
    }
    const node = document.getElementById('annotation-job-status');
    if (node) {
      const stage = {prepare: '准备输入', reveal: '构建画面', target_check: '检查同步', ink: '生成笔迹'}[job.stage] || '等待准备';
      node.style.display = 'inline-block'; node.textContent = `${stage} ${job.progress || 0}% `;
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.className = 'secondary compact-action-btn'; cancel.textContent = '停止预览准备';
      cancel.onclick = () => API.post(`${annotationsApiBase(projectId)}/jobs/${encodeURIComponent(saved.jobId)}/cancel`, {}, {silent: true})
        .catch(error => showToast(error.message));
      node.appendChild(cancel);
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

async function loadAnnotationPlayer() {
  if (window.AnnotationPlayer) return;
  if (!ANNOTATION_PREVIEW.loading) {
    ANNOTATION_PREVIEW.loading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/annotation_player.bundle.js?v=20261006.24';
      script.onload = resolve;
      script.onerror = () => { ANNOTATION_PREVIEW.loading = null; reject(new Error('预览播放器加载失败')); };
      document.head.appendChild(script);
    });
  }
  await ANNOTATION_PREVIEW.loading;
}

function annotationPrepareError(error) {
  const reasons = {
    anchor_unresolved: '所选词缺少可靠的自动时间，请在右侧试听并设置起笔点，或重新运行音频定位。',
    manual_calibration_stale: '音频已变化，旧人工起笔点需要重新试听。请记录当前播放位置后再次保存。',
    target_not_ready: '讲到所选内容时，画面目标尚未出现。请提前该内容的出现时间。',
    target_visibility_unresolved: '无法确定目标何时出现，请检查区域与 Mask 内容组的对应关系。',
    insufficient_draw_window: '页尾没有足够时间完整绘制，请缩短笔迹或提前起笔。',
    audio_timeline_missing: '本页没有音频时间轴，请先生成音频。',
    text_layout_missing: '文字布局缺失，请重新识别文字。',
    ink_build_failed: '墨迹生成失败，请重试。',
  };
  // 服务端拒绝复用过期预览结果(stale_preview)时,错误体只有机器码;
  // 必须翻译成人话,否则用户只会看到一段原始 JSON。
  if (error?.body?.detail?.code === 'stale_preview') {
    return '预览结果已过期（页面内容在生成后有变化），自动重新生成仍未成功，请再次点击同步预览。';
  }
  if (error?.body?.detail?.code === 'revision_conflict') {
    return '页面已被更新，请重新点击同步预览。';
  }
  const items = error?.body?.detail?.items || [];
  if (items.length) return items.map(item => {
    const times = item.reason === 'target_not_ready' && Number.isFinite(item.delay_sec)
      ? ` 讲稿 ${item.phrase_start_sec.toFixed(2)} 秒，目标 ${item.target_ready_sec.toFixed(2)} 秒，晚 ${item.delay_sec.toFixed(2)} 秒。` : '';
    return `${item.annotation_id || '本页'}：${reasons[item.reason] || item.reason}${times}`;
  }).join('\n');
  return error.message || '预览准备失败';
}

async function prepareAnnotationPreview() {
  await flushAnnotationsSave();
  if (annotationTriggerNeedsSelection()) throw new Error('请先关联讲稿或明确设置起笔时间。');
  if (ANNOTATIONS_WS.pendingOps.length || ANNOTATIONS_WS.failedOps.length || ANNOTATIONS_WS.conflict) {
    throw new Error('请先处理未保存的编辑。');
  }
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  const revision = ANNOTATIONS_WS.page.revision;
  const editGeneration = ANNOTATIONS_WS.editGeneration || 0;
  // 服务端在任务成功后会复核输入新鲜度,输入变化即拒绝复用结果(409
  // stale_preview)。此时自动丢弃缓存并用新任务重试一次,自愈"服务端
  // 已成功、界面却拿不到结果"的死端。
  let result;
  for (let attempt = 0; ; attempt += 1) {
    try {
      result = await waitAnnotationPreviewJob(projectId, slideId, revision);
      break;
    } catch (error) {
      const stale = error.status === 409 && error.body?.detail?.code === 'stale_preview';
      if (!stale || attempt >= 1) throw error;
      sessionStorage.removeItem(`annotation-preview:${projectId}:${slideId}`);
    }
  }
  window.flushAnnotationEditorEdits?.();
  if (editGeneration !== (ANNOTATIONS_WS.editGeneration || 0)
      || projectId !== ANNOTATIONS_WS.projectId || slideId !== ANNOTATIONS_WS.page.slide_id
      || revision !== ANNOTATIONS_WS.page.revision || ANNOTATIONS_WS.pendingOps.length) {
    throw new Error('页面已经更新，请重新预览。');
  }
  ANNOTATION_PREVIEW.prepared = {projectId, slideId, revision, result};
  return ANNOTATION_PREVIEW.prepared;
}

async function showAnnotationSyncPreview() {
  if (ANNOTATION_PREVIEW.busy) return;
  ANNOTATION_PREVIEW.busy = true;
  const generation = ++ANNOTATION_PREVIEW.generation;
  try {
    const prepared = await prepareAnnotationPreview();
    await loadAnnotationPlayer();
    if (generation !== ANNOTATION_PREVIEW.generation) return;
    const {projectId, slideId, result} = prepared;
    const subtitleSettings = await API.get(`/api/projects/${projectId}/subtitle-settings`);
    if (generation !== ANNOTATION_PREVIEW.generation) return;
    const base = `${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}`;
    const absolute = value => new URL(value, window.location.origin).href;
    const scene = JSON.parse(JSON.stringify(result.scene));
    const assetUrl = asset => absolute(`${base}/scene-asset?asset=${encodeURIComponent(asset)}`);
    scene.layers.forEach(layer => {layer.asset = assetUrl(layer.asset);});
    if (scene.canvas.background_asset) scene.canvas.background_asset = assetUrl(scene.canvas.background_asset);
    const timeline = JSON.parse(JSON.stringify(result.timeline));
    timeline.events.forEach(event => event.strokes.forEach((stroke, index) => {
      const ink = stroke.ink;
      ink.frames = Array.from({length: ink.frame_count}, (_, frame) => absolute(
        `${base}/ink/${timeline.build_id}/${event.annotation_id}/${index}/${frame}`));
    }));
    let dialog = document.getElementById('annotation-sync-preview');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'annotation-sync-preview';
      dialog.className = 'annotation-sync-preview';
      dialog.setAttribute('aria-labelledby', 'annotation-video-title');
      dialog.innerHTML = `<header class="annotation-video-header">
          <h2 id="annotation-video-title">标注预览</h2>
          <div class="annotation-preview-header-actions"><button type="button" id="annotation-video-download" class="secondary">下载预览 MP4</button><button id="annotation-video-close" type="button" class="secondary">关闭预览</button></div>
        </header>
        <div class="annotation-video-layout">
          <section class="annotation-video-stage" aria-label="同步视频">
            <div class="annotation-video-stage-heading"><span>视频预览</span></div>
            <div class="annotation-video-screen"><div id="annotation-player-root"></div></div>
            <div class="annotation-video-transport"><div class="annotation-video-frame-actions">
              <button type="button" id="annotation-video-prev" class="secondary">前一帧</button>
              <button type="button" id="annotation-video-next" class="secondary">后一帧</button>
            </div><output id="annotation-video-clock" aria-live="off"></output></div>
          </section>
          <aside class="annotation-video-inspector" aria-label="标注修正">
            <section class="annotation-video-section"><h3>当前标注</h3>
              <label for="annotation-video-item">关联的讲稿内容</label><select id="annotation-video-item"></select>
              <button type="button" id="annotation-video-jump" class="secondary">跳到起笔前</button>
            </section>
            <section class="annotation-video-section"><h3>校准起笔时间</h3>
              <button type="button" id="annotation-video-record" class="secondary">以当前视频位置起笔</button>
            </section>
            <section class="annotation-video-section"><h3>修正画面位置</h3>
              <div class="annotation-video-geometry-actions"><button type="button" id="annotation-video-region" class="secondary">修改范围</button>
                <button type="button" id="annotation-video-path" class="secondary">重画笔迹</button></div>
            </section>
          </aside>
        </div>
        <footer class="annotation-video-footer"><div><p id="annotation-video-change" role="status"></p></div>
          <button type="button" id="annotation-video-refresh" class="primary">保存并更新预览</button>
        </footer>`;
      dialog.querySelector('#annotation-video-close').onclick = () => dialog.close();
      dialog.addEventListener('close', () => {
        // 用户关闭对话框后,任何在途的准备/字幕请求都不得再把弹窗拉起来
        // (幽灵弹窗):递增 generation 使后续 continuation 全部失效。
        ++ANNOTATION_PREVIEW.generation;
        clearInterval(ANNOTATION_PREVIEW.clockTimer);
        window.AnnotationPlayer?.stop();
      });
      document.body.appendChild(dialog);
    }
    dialog.querySelector('#annotation-video-download').onclick = async event => {
      const button = event.currentTarget;
      button.disabled = true; button.textContent = '正在导出 MP4…';
      try {
        const exported = await API.post(`${base}/export-preview`, {expected_revision: result.revision, subtitle_style: subtitleSettings.subtitle_style}, {timeoutMs: 660000});
        const link = document.createElement('a'); link.href = exported.url; link.download = `${slideId}_annotation_preview.mp4`; link.click();
      } catch (error) { showToast(`预览导出失败：${error.message}`); }
      finally { button.disabled = false; button.textContent = '下载预览 MP4'; }
    };
    const [width, height] = timeline.canvas;
    window.AnnotationPlayer.mount(document.getElementById('annotation-player-root'), {
      subtitle_style: subtitleSettings.subtitle_style,
      slides: [{slide_id: slideId, start_sec: 0, duration_sec: timeline.slide_duration_sec,
        scene, audio_timeline: result.audio_timeline, animation_timeline: result.animation_timeline,
        audio_file: absolute(result.audio_url), annotation_timeline: timeline}],
    }, timeline.fps, timeline.slide_duration_sec, width, height);
    dialog.querySelector('.shared-video-tools')?.remove();
    window.attachVideoTools?.(dialog.querySelector('.annotation-video-screen'), {rate: n => window.AnnotationPlayer.rate(n), media: () => Array.from(dialog.querySelectorAll('audio,video'))});
    document.getElementById('annotation-calibration-audio')?.pause();
    const select = dialog.querySelector('#annotation-video-item');
    select.replaceChildren(...ANNOTATIONS_WS.page.items.filter(item => item.status?.content !== 'disabled').map(item => {
      const option = document.createElement('option'); option.value = item.annotation_id;
      option.textContent = item.anchor?.quote || item.annotation_id; return option;
    }));
    select.value = ANNOTATIONS_WS.selectedAnnotationId || select.options[0]?.value || '';
    const validContext = () => prepared.projectId === ANNOTATIONS_WS.projectId && prepared.slideId === ANNOTATIONS_WS.page.slide_id;
    const selected = () => ANNOTATIONS_WS.page.items.find(item => item.annotation_id === select.value);
    const seek = frame => {window.AnnotationPlayer.pause(); window.AnnotationPlayer.seek(Math.max(0, Math.min(Math.ceil(timeline.slide_duration_sec * timeline.fps) - 1, frame)));};
    dialog.querySelector('#annotation-video-prev').onclick = () => seek(window.AnnotationPlayer.frame() - 1);
    dialog.querySelector('#annotation-video-next').onclick = () => seek(window.AnnotationPlayer.frame() + 1);
    dialog.querySelector('#annotation-video-jump').onclick = () => {
      const item = selected(); const event = timeline.events.find(event => event.annotation_id === select.value);
      const start = item?.timing?.trigger_mode === 'manual' ? Number(item.timing.manual_start_sec) + (item.timing.time_reference === 'audio' ? Number(result.audio_timeline.audio_start_sec || 0) : 0) : event?.start_sec;
      if (Number.isFinite(start)) seek(Math.round(Math.max(0, start - .8) * timeline.fps));
    };
    dialog.querySelector('#annotation-video-record').onclick = () => {
      if (!validContext()) {showToast('页面已切换，请重新打开预览。'); return;}
      window.AnnotationPlayer.pause();
      const audioTime = annotationVideoAudioTime(window.AnnotationPlayer.frame(), timeline.fps, result.audio_timeline, timeline.slide_duration_sec);
      if (audioTime === null) {showToast('请定位到语音开始之后、结束之前。'); return;}
      if (window.setAnnotationVideoStart?.(select.value, audioTime)) dialog.querySelector('#annotation-video-change').textContent = '起笔时间已修改；当前播放的仍是旧预览，请点击“保存并更新预览”核对完整笔迹。';
    };
    for (const [id, mode] of [['region', 'region'], ['path', 'freehand']]) dialog.querySelector(`#annotation-video-${id}`).onclick = () => {
      if (!validContext() || !selected()) return;
      ANNOTATIONS_WS.selectedAnnotationId = select.value;
      dialog.close(); renderAnnotationItemEditor(); beginAnnotationRepair(mode);
    };
    dialog.querySelector('#annotation-video-refresh').onclick = async () => {
      if (!validContext()) return;
      dialog.close(); await showAnnotationSyncPreview();
    };
    clearInterval(ANNOTATION_PREVIEW.clockTimer);
    ANNOTATION_PREVIEW.clockTimer = setInterval(() => {
      const pageTime = window.AnnotationPlayer.frame() / timeline.fps;
      dialog.querySelector('#annotation-video-clock').textContent = `视频 ${pageTime.toFixed(3)} 秒 · 语音 ${(pageTime - Number(result.audio_timeline.audio_start_sec || 0)).toFixed(3)} 秒`;
    }, 100);
    if (!dialog.open) dialog.showModal();
  } catch (error) {
    showToast(annotationPrepareError(error));
  } finally {
    ANNOTATION_PREVIEW.busy = false;
    const node = document.getElementById('annotation-job-status');
    // 同时清空文本:隐藏但残留"构建画面 10%"会在后续观察中被误读为仍在进行。
    if (node) { node.style.display = 'none'; node.textContent = ''; }
  }
}

function stopAnnotationSyncPreview() {
  ++ANNOTATION_PREVIEW.generation;
  window.AnnotationPlayer?.stop();
  document.getElementById('annotation-sync-preview')?.close();
}

window.showAnnotationSyncPreview = showAnnotationSyncPreview;
window.stopAnnotationSyncPreview = stopAnnotationSyncPreview;
