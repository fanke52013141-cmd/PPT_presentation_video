(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_one_click_project_id') || '',
    polling: null,
  };

  function parseJsonResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(parseJsonResponse);
  }

  function apiPost(url, body) {
    return window.API?.post
      ? window.API.post(url, body || {})
      : fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {}),
        }).then(parseJsonResponse);
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  function rememberProjectId(projectId) {
    if (!projectId) return;
    STATE.projectId = String(projectId);
    sessionStorage.setItem('ppt_one_click_project_id', STATE.projectId);
  }

  function activeProjectId() {
    return STATE.projectId || sessionStorage.getItem('ppt_one_click_project_id') || '';
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__oneClickPatched) {
        const originalEnter = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await originalEnter.apply(this, arguments);
          ensureEntryButton();
          refreshStatusSilently();
          return result;
        };
        window.enterWorkspace.__oneClickPatched = true;
      }
      if (window.exitWorkspace && !window.exitWorkspace.__oneClickPatched) {
        const originalExit = window.exitWorkspace;
        window.exitWorkspace = function patchedExitWorkspace() {
          STATE.projectId = '';
          sessionStorage.removeItem('ppt_one_click_project_id');
          stopPolling();
          return originalExit.apply(this, arguments);
        };
        window.exitWorkspace.__oneClickPatched = true;
      }
    };
    patch();
    const timer = setInterval(() => {
      patch();
      if (window.enterWorkspace?.__oneClickPatched) clearInterval(timer);
    }, 500);
  }


  function ensureModal() {
    if (document.getElementById('modal-one-click-generate')) return;
    const modal = document.createElement('div');
    modal.id = 'modal-one-click-generate';
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content one-click-modal">
        <h3 class="highlight-title">一键生成</h3>
        <p class="one-click-note"><strong>一键生成会读取当前各步骤配置：</strong>从已导入文章开始，自动完成文章➡️slides、slides➡️可视化、图片生成、AI Mask、旁白与音频以及最终视频合成。失败时会保留阶段状态，重新运行时复用未过期产物。</p>
        <div class="one-click-toolbar">
          <button id="btn-one-click-start" class="success" type="button">重新运行自动生成</button>
          <button id="btn-one-click-refresh" class="secondary" type="button">刷新状态</button>
          <button id="btn-one-click-close" class="secondary" type="button">关闭</button>
        </div>
        <div id="one-click-status" class="one-click-status-line">尚未读取状态。</div>
        <div id="one-click-stages" class="one-click-stage-list"></div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-one-click-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-one-click-refresh')?.addEventListener('click', () => refreshStatus().catch(error => toast(`刷新失败：${error.message}`, 6000)));
    document.getElementById('btn-one-click-start')?.addEventListener('click', startOneClick);
  }

  function ensureEntryButton() {
    ensureModal();
    const stepper = document.querySelector('.sidebar .stepper');
    if (!stepper || document.getElementById('btn-one-click-generate')) return;
    const entry = document.createElement('li');
    entry.className = 'one-click-sidebar-entry';
    const button = document.createElement('button');
    button.id = 'btn-one-click-generate';
    button.className = 'success';
    button.type = 'button';
    button.innerHTML = '<span aria-hidden="true">✦</span><span>一键生成</span>';
    button.addEventListener('click', () => openModal().catch(error => toast(`打开失败：${error.message}`, 6000)));
    entry.appendChild(button);
    stepper.appendChild(entry);
  }

  function renderStatus(status) {
    const summary = document.getElementById('one-click-status');
    const stages = document.getElementById('one-click-stages');
    if (!summary || !stages) return;
    const state = status?.status || 'idle';
    const current = status?.current_stage || '';
    const activity = document.getElementById('project-activity-status');
    if (activity) {
      const currentStage = (status?.stages || []).find(stage => stage.id === current);
      const message = currentStage?.title || currentStage?.message || '';
      activity.innerHTML = state === 'running'
        ? `<span class="button-spinner"></span><span>${esc(message || '一键生成运行中')}</span>`
        : state === 'completed'
          ? '<span>一键生成已完成</span>'
          : '';
      activity.classList.toggle('active', state === 'running' || state === 'completed');
      activity.classList.toggle('running', state === 'running');
    }
    summary.innerHTML = `
      <strong>状态：</strong><span class="one-click-pill ${esc(state)}">${esc(state)}</span>
      ${current ? `<span style="margin-left:.5rem;">当前阶段：${esc(current)}</span>` : ''}
      ${status?.started_at ? `<br><small>开始：${esc(status.started_at)}　更新：${esc(status.updated_at || '')}</small>` : ''}
      ${status?.video?.url ? `<br><a href="${esc(status.video.url)}" target="_blank">打开生成视频</a>` : ''}
    `;
    const list = Array.isArray(status?.stages) ? status.stages : [];
    stages.innerHTML = list.map(stage => {
      const errors = Array.isArray(stage.blocking_errors) && stage.blocking_errors.length ? `<small>错误：${esc(stage.blocking_errors.join(' / '))}</small>` : '';
      const warnings = Array.isArray(stage.warnings) && stage.warnings.length ? `<small>警告：${esc(stage.warnings.join(' / '))}</small>` : '';
      return `
        <article class="one-click-stage">
          <strong>${esc(stage.title || stage.id)} <span>${stage.status === 'running' ? '<span class="button-spinner"></span>' : ''}<span class="one-click-pill ${esc(stage.status || 'pending')}">${esc(stage.status || 'pending')}</span></span></strong>
          <small>${esc(stage.message || '')}</small>
          ${warnings}${errors}
        </article>
      `;
    }).join('');
  }

  async function refreshStatus() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目，请先进入项目工作区。');
    const result = await apiGet(`/api/projects/${projectId}/one-click-generate/status`);
    renderStatus(result.status || {});
    const state = result.status?.status;
    if (state === 'running') startPolling();
    else stopPolling();
    return result.status;
  }

  function refreshStatusSilently() {
    refreshStatus().catch(() => {});
  }

  async function startOneClick() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const currentStatus = await refreshStatus();
    const resume = currentStatus?.status === 'paused';
    const confirmed = window.confirm(resume
      ? '将从上次失败阶段继续，并保护已锁定或人工修正的 Mask、旁白和未过期产物。继续？'
      : '将运行自动生成流程，并保护已锁定或人工修正的 Mask、旁白和未过期产物。继续？');
    if (!confirmed) return;
    const button = document.getElementById('btn-one-click-start');
    const original = button?.textContent || '重新运行自动生成';
    if (button) {
      button.disabled = true;
      button.textContent = '启动中...';
    }
    try {
      const result = await apiPost(`/api/projects/${projectId}/one-click-generate`, { mode: resume ? 'resume' : 'restart' });
      renderStatus(result.status || {});
      toast(result.already_running ? '一键生成正在运行。' : '自动生成已启动。', 4000);
      startPolling();
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  async function openModal() {
    ensureModal();
    const modal = document.getElementById('modal-one-click-generate');
    if (modal) modal.style.display = 'flex';
    await refreshStatus();
  }

  function closeModal() {
    const modal = document.getElementById('modal-one-click-generate');
    if (modal) modal.style.display = 'none';
  }

  function startPolling() {
    if (STATE.polling) return;
    STATE.polling = setInterval(() => refreshStatusSilently(), 2500);
  }

  function stopPolling() {
    if (STATE.polling) clearInterval(STATE.polling);
    STATE.polling = null;
  }

  function boot() {
    patchWorkspaceNavigation();
    ensureEntryButton();
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
