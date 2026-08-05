// Visible Step 6 output workspace: PPTX export, video rendering, persistent-job polling,
// artifact presentation/removal, and playback-speed variants.
// Shared project state, API helpers, confirmation UI, and workflow refresh live in ui_foundation.js / workflow_state.js / api_client.js.

// ==================== 步骤 8: 视频合成与渲染 ====================

// 渲染任务轮询状态。渲染耗时较长（5-60 分钟），后端用后台线程跑，
// 前端通过 render-status 路由轮询，避免长连接被浏览器超时断开报 "Failed to fetch"。
let _step8RenderPollTimer = null;
let _step8RenderTaskId = null;

function updateStep8LoadingText(stageLabel, elapsedSec) {
  const text = document.getElementById('step8-loading-text');
  if (!text) return;
  const stage = stageLabel ? stageLabel : '视频渲染中';
  const elapsed = (elapsedSec != null && elapsedSec > 0)
    ? `（已用 ${Math.round(elapsedSec)} 秒）`
    : '';
  text.innerText = `${stage}${elapsed}...`;
}

function stopStep8RenderPolling() {
  if (_step8RenderPollTimer) {
    clearInterval(_step8RenderPollTimer);
    _step8RenderPollTimer = null;
  }
  _step8RenderTaskId = null;
}

function startStep8RenderPolling(taskId) {
  // 防止重复启动
  if (_step8RenderPollTimer) clearInterval(_step8RenderPollTimer);
  _step8RenderTaskId = taskId;

  const poll = async () => {
    try {
      const url = `/api/projects/${state.currentProject.id}/steps/8/render-status?task_id=${encodeURIComponent(taskId)}`;
      const res = await API.get(url);
      if (!res.success) return;

      if (res.status === 'rendering') {
        updateStep8LoadingText(res.stage_label, res.elapsed_sec);
        return;
      }

      // 终态：success / error / idle
      stopStep8RenderPolling();
      document.getElementById('step8-loading').style.display = 'none';
      const renderBtn = document.getElementById('step8-btn-render');
      if (renderBtn) renderBtn.disabled = false;

      if (res.status === 'success') {
        showToast('🎉 视频渲染成功！');
        showStep8VideoResult(res.videos || (res.video ? [res.video] : []));
        refreshCurrentProjectStatus(8).catch(() => {});
      } else if (res.status === 'error') {
        const message = res.error || '视频渲染失败，请查看 logs/pipeline.log。';
        setStep8OutputError('视频渲染失败', message, { showLog: true });
        showToast(`❌ 渲染失败: ${message}`, 7000);
      } else if (res.status === 'interrupted') {
        const message = res.error || '应用上次运行时退出，视频任务已中断，请重新生成。';
        setStep8OutputError('视频任务已中断', message);
        showToast(message, 7000);
      } else if (res.status === 'idle') {
        // 任务记录丢失（可能服务器重启），刷新视频列表
        if (res.videos && res.videos.length > 0) {
          showStep8VideoResult(res.videos);
        }
      }
    } catch (e) {
      console.error('Step 8 status poll failed:', e);
      // 网络错误不停止轮询，下一轮重试
    }
  };

  // 立即轮询一次
  poll();
  // 每 3 秒轮询
  _step8RenderPollTimer = setInterval(poll, 3000);
}

async function loadStep8Data() {
  await loadStep8PptxData();
  try {
    // 先检查是否有进行中的渲染任务（页面刷新后恢复轮询）
    const statusRes = await API.get(`/api/projects/${state.currentProject.id}/steps/8/render-status`);
    if (statusRes.success && statusRes.status === 'rendering') {
      document.getElementById('step8-loading').style.display = 'inline-flex';
      updateStep8LoadingText(statusRes.stage_label, statusRes.elapsed_sec);
      const renderBtn = document.getElementById('step8-btn-render');
      if (renderBtn) renderBtn.disabled = true;
      startStep8RenderPolling(statusRes.task_id);
      // 同时显示已有视频
      if (statusRes.videos && statusRes.videos.length > 0) {
        showStep8VideoResult(statusRes.videos);
      }
      return;
    }
    if (statusRes.success && (statusRes.status === 'interrupted' || statusRes.status === 'error')) {
      setStep8OutputError(
        statusRes.status === 'interrupted' ? '视频任务已中断' : '上次视频生成失败',
        statusRes.error || '请重新生成视频。',
      );
    }

    const res = await API.get(`/api/projects/${state.currentProject.id}/videos`);
    if (res.success && Array.isArray(res.videos) && res.videos.length > 0) {
      showStep8VideoResult(res.videos);
    } else {
      document.getElementById('step8-result-box').style.display = 'none';
      document.getElementById('step8-btn-render').style.display = 'inline-flex';
    }
  } catch (e) {
    document.getElementById('step8-result-box').style.display = 'none';
    document.getElementById('step8-btn-render').style.display = 'inline-flex';
  }
}

async function runStep8Render() {
  const renderBtn = document.getElementById('step8-btn-render');
  document.getElementById('step8-loading').style.display = 'inline-flex';
  document.getElementById('step8-loading-text').innerText = '视频渲染中...';
  document.getElementById('step8-error-box').style.display = 'none';
  if (renderBtn) renderBtn.disabled = true;
  showToast('🎬 Remotion 渲染进程已启动，请稍候片刻...');

  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/8/render`);
    if (res.success && res.task_id) {
      // 异步任务已启动，开始轮询
      updateStep8LoadingText(res.stage_label, res.elapsed_sec);
      startStep8RenderPolling(res.task_id);
    } else if (res.success && res.videos) {
      // 已有渲染任务在进行中，直接显示当前视频列表
      showStep8VideoResult(res.videos);
      document.getElementById('step8-loading').style.display = 'none';
      if (renderBtn) renderBtn.disabled = false;
    }
  } catch(e) {
    console.error('Step 8 render start failed:', e);
    const message = e?.message || '视频渲染启动失败，请查看项目 logs/pipeline.log。';
    setStep8OutputError('视频渲染失败', message, { showLog: true });
    document.getElementById('step8-loading').style.display = 'none';
    if (renderBtn) renderBtn.disabled = false;
    showToast(`❌ 渲染失败: ${message}`, 7000);
  }
}

let _step8PptxPollTimer = null;
let _step8PptxJobId = null;

function stopStep8PptxPolling() {
  if (_step8PptxPollTimer) {
    clearInterval(_step8PptxPollTimer);
    _step8PptxPollTimer = null;
  }
  _step8PptxJobId = null;
}

function formatArtifactBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '未知大小';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function pptxStageLabel(stage) {
  return ({
    queued: '等待生成',
    validating: '检查页面',
    composing: '写入幻灯片',
    verifying: '校验 PPTX',
    completed: '生成完成',
  })[stage] || '生成 PPTX';
}

function setStep8OutputError(title, message, options = {}) {
  const titleNode = document.getElementById('step8-error-title');
  const messageNode = document.getElementById('step8-error-message');
  const logHint = document.getElementById('step8-error-log-hint');
  const box = document.getElementById('step8-error-box');
  if (titleNode) titleNode.innerText = title || '输出失败';
  if (messageNode) messageNode.innerText = message || '输出失败，请重试。';
  if (logHint) logHint.style.display = options.showLog ? 'block' : 'none';
  if (box) box.style.display = 'block';
}

function updateStep8PptxLoading(job) {
  const loading = document.getElementById('step8-pptx-loading');
  const text = document.getElementById('step8-pptx-loading-text');
  const button = document.getElementById('step8-btn-pptx');
  if (loading) loading.style.display = 'inline-flex';
  if (button) button.disabled = true;
  if (text) {
    const progress = Number(job?.progress || 0);
    text.innerText = `${pptxStageLabel(job?.stage)}${progress > 0 ? ` · ${progress}%` : ''}...`;
  }
}

function startStep8PptxPolling(jobId) {
  stopStep8PptxPolling();
  _step8PptxJobId = jobId;
  const poll = async () => {
    if (!state.currentProject || _step8PptxJobId !== jobId) return;
    try {
      const res = await API.get(
        `/api/projects/${state.currentProject.id}/jobs/${encodeURIComponent(jobId)}`,
      );
      const job = res.job || {};
      if (job.status === 'queued' || job.status === 'running') {
        updateStep8PptxLoading(job);
        return;
      }
      stopStep8PptxPolling();
      document.getElementById('step8-pptx-loading').style.display = 'none';
      if (job.status === 'succeeded') {
        showToast('PPTX 已生成，可以下载。');
        await loadStep8PptxData();
        refreshCurrentProjectStatus(8).catch(() => {});
      } else {
        setStep8OutputError(
          job.status === 'interrupted' ? 'PPTX 任务已中断' : 'PPTX 生成失败',
          job.error || '生成失败，请重新生成。',
        );
        await refreshStep8PptxReadiness();
      }
    } catch (error) {
      console.error('PPTX job polling failed:', error);
    }
  };
  poll();
  _step8PptxPollTimer = setInterval(poll, 1200);
}

async function refreshStep8PptxReadiness() {
  const button = document.getElementById('step8-btn-pptx');
  const label = document.getElementById('step8-pptx-readiness');
  if (!state.currentProject || !button || !label) return null;
  const readiness = await API.get(
    `/api/projects/${state.currentProject.id}/exports/pptx/readiness`,
  );
  label.classList.toggle('ready', readiness.ready === true);
  label.classList.toggle('blocked', readiness.ready !== true);
  if (readiness.ready) {
    label.innerText = `${readiness.slide_count} 页图片已就绪`;
    label.title = '可以生成图片型 PPTX';
    button.disabled = Boolean(_step8PptxJobId);
  } else {
    const issues = Array.isArray(readiness.issues) ? readiness.issues : [];
    label.innerText = issues[0]?.message || 'PPTX 尚未就绪';
    label.title = issues.map(item => item.message).filter(Boolean).join('\n');
    button.disabled = true;
  }
  return readiness;
}

async function loadStep8PptxData() {
  if (!state.currentProject) return;
  try {
    const [readiness, exportsResult, jobsResult] = await Promise.all([
      refreshStep8PptxReadiness(),
      API.get(`/api/projects/${state.currentProject.id}/exports`),
      API.get(`/api/projects/${state.currentProject.id}/jobs?job_type=pptx_export`),
    ]);
    showStep8PptxResults(exportsResult.artifacts || []);
    const active = (jobsResult.jobs || []).find(job => (
      job.status === 'queued' || job.status === 'running'
    ));
    if (active) {
      updateStep8PptxLoading(active);
      startStep8PptxPolling(active.id);
    } else {
      stopStep8PptxPolling();
      const loading = document.getElementById('step8-pptx-loading');
      if (loading) loading.style.display = 'none';
      const button = document.getElementById('step8-btn-pptx');
      if (button) button.disabled = !readiness?.ready;
    }
  } catch (error) {
    console.error('Load PPTX exports failed:', error);
    const label = document.getElementById('step8-pptx-readiness');
    if (label) {
      label.className = 'step8-readiness blocked';
      label.innerText = 'PPTX 状态读取失败';
    }
  }
}

async function runStep8PptxExport() {
  const button = document.getElementById('step8-btn-pptx');
  if (!state.currentProject || button?.disabled) return;
  if (button) button.disabled = true;
  document.getElementById('step8-error-box').style.display = 'none';
  updateStep8PptxLoading({ status: 'queued', stage: 'queued', progress: 0 });
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/exports/pptx`, {});
    if (!res.job?.id) throw new Error('服务器没有返回 PPTX 任务编号');
    showToast(res.reused ? '已有 PPTX 任务正在进行。' : 'PPTX 生成任务已启动。');
    startStep8PptxPolling(res.job.id);
  } catch (error) {
    document.getElementById('step8-pptx-loading').style.display = 'none';
    setStep8OutputError('PPTX 无法生成', error.message);
    await refreshStep8PptxReadiness().catch(() => {});
  }
}

function showStep8PptxResults(artifacts) {
  const box = document.getElementById('step8-pptx-result-box');
  const list = document.getElementById('step8-pptx-list');
  if (!box || !list) return;
  const items = Array.isArray(artifacts) ? artifacts : [];
  if (!items.length) {
    box.style.display = 'none';
    list.innerHTML = '';
    return;
  }
  list.innerHTML = items.map((item, index) => {
    const created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
    const stateBadge = item.artifact_state === 'current'
      ? '<span class="step8-current-badge">当前内容</span>'
      : item.artifact_state === 'stale'
        ? '<span class="step8-legacy-badge">输入已变化</span>'
        : '<span class="step8-legacy-badge">文件已缺失</span>';
    return `
      <article class="step8-pptx-card">
        <div class="step8-pptx-icon" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 13h8M8 17h5"></path></svg>
        </div>
        <div class="step8-pptx-main">
          <div class="step8-pptx-name">
            <strong>${index === 0 ? '最新 PPTX' : `历史 PPTX ${index + 1}`}</strong>
            ${stateBadge}
          </div>
          <div class="step8-pptx-meta">
            <span>${Number(item.slide_count || 0)} 页</span>
            <span>${formatArtifactBytes(item.size_bytes)}</span>
            <span>${escHtml(created || item.filename || '')}</span>
          </div>
        </div>
        <div class="step8-pptx-actions">
          ${item.exists ? `
            <a href="${item.download_url}" download class="btn success">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 3v12"></path></svg>
              下载 PPTX
            </a>
          ` : ''}
          <button class="danger compact-action-btn step8-pptx-delete" type="button" data-artifact-id="${escHtml(item.id || '')}">
            删除
          </button>
        </div>
      </article>
    `;
  }).join('');
  list.querySelectorAll('.step8-pptx-delete').forEach(button => {
    button.addEventListener('click', () => deleteStep8Pptx(button.dataset.artifactId || ''));
  });
  box.style.display = 'block';
}

function deleteStep8Pptx(artifactId) {
  if (!artifactId) return;
  showCustomConfirm(
    '删除 PPTX',
    '确定删除这个本地 PPTX 文件吗？删除后无法恢复。',
    async () => {
      const res = await API.delete(
        `/api/projects/${state.currentProject.id}/exports/${encodeURIComponent(artifactId)}`,
      );
      showStep8PptxResults(res.artifacts || []);
      showToast('PPTX 已删除。');
    },
  );
}

function showStep8VideoResult(videos) {
  document.getElementById('step8-btn-render').style.display = 'inline-flex';
  const list = document.getElementById('step8-video-list');
  if (!list) return;
  const items = Array.isArray(videos) ? videos : [];
  if (!items.length) {
    list.innerHTML = '<div class="soft-outline step6-empty-state">暂无渲染记录。</div>';
  } else {
    list.innerHTML = items.map((item, idx) => {
      const url = `${item.url}?t=${Date.now()}`;
      const created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
      const playbackRate = Number(item.playback_rate || 1);
      const speedLabel = `${playbackRate.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')}×`;
      const artifactBadge = item.artifact_state === 'current'
        ? '<span class="step8-current-badge">精确 RLE Mask v5 · 当前</span>'
        : item.artifact_state === 'stale'
          ? '<span class="step8-legacy-badge">输入已变化 · 需重渲染</span>'
          : item.artifact_state === 'invalid'
            ? '<span class="step8-legacy-badge">元数据损坏</span>'
            : '<span class="step8-legacy-badge">历史版本 · 状态未知</span>';
      return `
        <div class="step8-video-card">
          <div class="step8-video-card-head">
            <strong>
              ${idx === 0 ? '最新渲染' : `历史版本 ${idx + 1}`}
              ${item.is_speed_variant ? `<span class="step8-speed-badge">${escHtml(speedLabel)} 调速版</span>` : ''}
              ${artifactBadge}
            </strong>
            <span>${escHtml(created || item.filename || '')}</span>
          </div>
          <div class="video-preview-box">
            <video controls src="${escHtml(url)}" data-video-filename="${escHtml(item.filename || '')}"></video>
          </div>
          <div class="step8-video-actions">
            ${item.is_speed_variant ? `
              <span class="step8-speed-source">已按 ${escHtml(speedLabel)} 生成，可直接下载</span>
            ` : `
              <label class="step8-speed-control">
                <span>视频语速</span>
                <select class="step8-speed-select" data-filename="${escHtml(item.filename || '')}">
                  ${[0.75, 1, 1.25, 1.5, 2].map(rate => `<option value="${rate}" ${rate === 1 ? 'selected' : ''}>${rate}×</option>`).join('')}
                </select>
              </label>
              <button class="secondary compact-action-btn step8-speed-generate" type="button" data-filename="${escHtml(item.filename || '')}">
                应用语速并生成 MP4
              </button>
            `}
            <a href="${escHtml(item.url)}" download class="btn success" style="text-decoration: none;">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 3v12"></path></svg>
              下载 MP4
            </a>
            <button class="danger compact-action-btn step8-video-delete" type="button" data-filename="${escHtml(item.filename || '')}">
              删除视频
            </button>
          </div>
        </div>
      `;
    }).join('');
    list.querySelectorAll('.step8-speed-select').forEach(select => {
      select.addEventListener('change', () => {
        const card = select.closest('.step8-video-card');
        const video = card?.querySelector('video');
        if (video) video.playbackRate = Number(select.value || 1);
      });
    });
    list.querySelectorAll('.step8-speed-generate').forEach(button => {
      button.addEventListener('click', () => {
        const card = button.closest('.step8-video-card');
        const select = card?.querySelector('.step8-speed-select');
        generateStep8SpeedVideo(button.dataset.filename || '', Number(select?.value || 1), button);
      });
    });
    list.querySelectorAll('.step8-video-delete').forEach(button => {
      button.addEventListener('click', () => {
        deleteStep8Video(button.dataset.filename || '');
      });
    });
  }
  document.getElementById('step8-result-box').style.display = 'block';
}

async function generateStep8SpeedVideo(filename, speed, button) {
  if (!filename || !Number.isFinite(speed)) return;
  if (Math.abs(speed - 1) < 0.001) {
    showToast('当前是 1× 原速，直接点击“下载 MP4”即可。');
    return;
  }
  const originalText = button?.textContent || '应用语速并生成 MP4';
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="button-spinner"></span> 正在生成调速版...';
  }
  try {
    const res = await API.post(
      `/api/projects/${state.currentProject.id}/videos/${encodeURIComponent(filename)}/speed`,
      { speed },
    );
    if (res.success) {
      showStep8VideoResult(res.videos || (res.video ? [res.video] : []));
      showToast(`已生成 ${speed}× 调速版，下载按钮会下载调速后的 MP4。`);
    }
  } catch (error) {
    showToast(`调速视频生成失败：${error.message}`, 7000);
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function deleteStep8Video(filename) {
  if (!filename) return;
  showCustomConfirm(
    '删除渲染视频',
    `确定删除本地视频 ${filename} 吗？删除后无法恢复。`,
    async () => {
      const res = await API.delete(`/api/projects/${state.currentProject.id}/videos/${encodeURIComponent(filename)}`);
      if (res.success) {
        showStep8VideoResult(res.videos || []);
        showToast('本地视频已删除。');
      }
    }
  );
}

window.deleteStep8Video = deleteStep8Video;
window.deleteStep8Pptx = deleteStep8Pptx;

