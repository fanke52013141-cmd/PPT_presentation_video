(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_one_click_project_id') || '',
    polling: null,
    lastFollowedStage: '',
    // [轮询自愈 20260904] 记录连续失败次数、最近一次成功刷新时间、后台跳过
    // 计数与连接告警去重标记，用于连接中断提示与陈旧状态指示。
    failCount: 0,
    lastRefreshAt: 0,
    hiddenSkip: 0,
    connAlertShown: false,
  };

  // [轮询自愈 20260904] 连续失败达到该阈值（约 7.5 秒无响应）才展示连接
  // 中断提示：瞬时网络抖动（1~2 次）不打扰用户，服务重启期间明确告知
  // "正在自动重试"，避免画面停留在旧状态被误读为流程卡住。
  const POLL_FAIL_ALERT_THRESHOLD = 3;
  // [轮询自愈 20260904] 页面隐藏时保留的轮询心跳上限：浏览器对后台标签页
  // 的定时器有分钟级节流，若 tick 仍被触发则以少量心跳检测任务终态。
  const POLL_MAX_HIDDEN_SKIP = 4;

  // [自动模式跟随 20260813] 后端 stage id -> 左侧菜单 data-step 映射
  const STAGE_TO_STEP = {
    preflight: 1,
    storyboard: 2,
    images: 3,
    confirm_images: 3,
    ai_mask: 5,
    mask_assets: 5,
    narration: 6,
    tts: 6,
    render: 8,
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

  // [自动模式跟随 20260904]
  // 一键生成运行时只刷新左侧菜单高亮/完成态，不再强制切换步骤面板：
  // 长耗时阶段（TTS 合成可达十余分钟、Remotion 渲染）期间强制跟随会把
  // 用户"锁"在当前面板，造成"跳不过去"的观感。当前进行中的阶段改由
  // 顶部活动状态条与一键弹窗展示，用户可自由浏览已解锁步骤。
  function followActiveStage(status) {
    const runState = (status && status.status) || 'idle';
    if (runState !== 'running') {
      STATE.lastFollowedStage = '';
      return;
    }
    const stage = (status && status.current_stage) || '';
    if (!stage || stage === STATE.lastFollowedStage) return;
    STATE.lastFollowedStage = stage;
    if (typeof window.refreshCurrentProjectStatus === 'function') {
      try { window.refreshCurrentProjectStatus(); } catch (e) { /* 刷新失败不阻断轮询 */ }
    }
  }

  // [一键进度出口 20260904] 一键生成运行时，把当前阶段进度注入对应步骤面板顶部。
  // 长耗时阶段（TTS 合成可达十余分钟、Remotion 渲染更久）期间，面板内确认按钮
  // 处于禁用态；没有进度出口时用户会误以为界面卡死。横幅提供真实阶段消息与
  // "查看进度"入口（打开一键弹窗），并明确提示可自由浏览其他已解锁步骤。
  function renderStageProgressInPanel(status) {
    const bannerId = 'one-click-stage-progress-banner';
    let banner = document.getElementById(bannerId);
    const runState = (status && status.status) || 'idle';
    const stage = (status && status.current_stage) || '';
    const targetStep = STAGE_TO_STEP[stage] || 0;
    const panel = targetStep ? document.getElementById(`step-panel-${targetStep}`) : null;
    if (runState !== 'running' || !panel) {
      if (banner) banner.remove();
      return;
    }
    if (!banner) {
      banner = document.createElement('div');
      banner.id = bannerId;
      banner.className = 'one-click-stage-progress-banner';
      banner.addEventListener('click', event => {
        if (event.target.closest('button')) {
          openModal().catch(error => toast(`打开失败：${error.message}`, 6000));
        }
      });
      panel.prepend(banner);
    }
    const stageItem = (status?.stages || []).find(item => item.id === stage);
    const message = stageItem?.message || stageItem?.title || '处理中';
    const summary = `<span class="button-spinner"></span><span>一键生成进行中：${esc(message)}</span>`;
    const current = banner.dataset.summary || '';
    if (current !== summary) {
      banner.dataset.summary = summary;
      banner.innerHTML = `${summary}<span class="one-click-stage-progress-hint">可先浏览其他已解锁步骤，后台会自动继续</span><button type="button" class="secondary compact-action-btn">查看进度</button>`;
    }
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
          <button id="btn-one-click-start" class="success" type="button">智能继续</button>
          <button id="btn-one-click-restart" class="secondary" type="button">从头重跑</button>
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
    document.getElementById('btn-one-click-start')?.addEventListener('click', () => startOneClick('resume').catch(error => toast(`启动失败：${error.message}`, 6000)));
    document.getElementById('btn-one-click-restart')?.addEventListener('click', () => startOneClick('restart').catch(error => toast(`启动失败：${error.message}`, 6000)));
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
    // [轮询自愈 20260904] 本地数据新鲜度：running 态下轮询每 2.5 秒重渲染，
    // 该数字会持续滚动；切后台导致的滞后一眼可辨。
    const freshNote = STATE.lastRefreshAt
      ? `页面数据刷新于 ${Math.max(0, Math.round((Date.now() - STATE.lastRefreshAt) / 1000))} 秒前`
      : '';
    const activity = document.getElementById('project-activity-status');
    if (activity) {
      const currentStage = (status?.stages || []).find(stage => stage.id === current);
      const message = currentStage?.title || currentStage?.message || '';
      // [完成基准 20260904] 一键生成的完成以视频产出为基准：
      // 后端保证 completed 时 status.video.url 存在；前端双保险，
      // 拿不到视频链接时不显示"已完成"，避免渲染仍在后台跑时误报。
      const finished = state === 'completed' && !!status?.video?.url;
      activity.innerHTML = state === 'running'
        ? `<span class="button-spinner"></span><span>${esc(message || '一键生成运行中')}</span>`
        : finished
          ? '<span>一键生成已完成</span>'
          : '';
      activity.classList.toggle('active', state === 'running' || finished);
      activity.classList.toggle('running', state === 'running');
    }
    summary.innerHTML = `
      <strong>状态：</strong><span class="one-click-pill ${esc(state)}">${esc(state)}</span>
      ${current ? `<span style="margin-left:.5rem;">当前阶段：${esc(current)}</span>` : ''}
      ${status?.effective_start_stage ? `<br><small>恢复计划：从 ${esc(status.effective_start_stage)} 开始</small>` : ''}
      ${status?.started_at ? `<br><small>开始：${esc(status.started_at)}　更新：${esc(status.updated_at || '')}</small>` : ''}
      ${freshNote ? `<br><small>${freshNote}</small>` : ''}
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
    // [自动模式跟随 20260904] 只刷新左侧菜单完成态，不再强制切换面板
    followActiveStage(status);
    // [一键进度出口 20260904] 面板内注入当前阶段进度横幅
    renderStageProgressInPanel(status);
  }

  async function refreshStatus() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目，请先进入项目工作区。');
    const result = await apiGet(`/api/projects/${encodeURIComponent(projectId)}/one-click-generate/status`);
    // [轮询自愈 20260904] 任一路径成功即视为链路恢复：
    // 重置连续失败计数与连接告警标记，并记录本地刷新时刻供新鲜度展示。
    STATE.failCount = 0;
    STATE.connAlertShown = false;
    STATE.lastRefreshAt = Date.now();
    renderStatus(result.status || {});
    const state = result.status?.status;
    if (state === 'running') startPolling();
    else stopPolling();
    return result.status;
  }

  // [轮询自愈 20260904] 连接中断提示：连续失败达到阈值后写入顶部活动状态条
  // 与一键弹窗摘要。成功刷新时 renderStatus 会整体重写这两个区域，提示随之
  // 自动消失，无需专门的清除逻辑。connAlertShown 做去重，避免每个 tick 重复
  // 写 DOM。
  function renderConnectionAlert() {
    if (STATE.failCount < POLL_FAIL_ALERT_THRESHOLD || STATE.connAlertShown) return;
    STATE.connAlertShown = true;
    const activity = document.getElementById('project-activity-status');
    if (activity) {
      activity.innerHTML = '<span class="one-click-conn-alert">与服务器失去连接，正在自动重试…</span>';
      activity.classList.add('active');
      activity.classList.remove('running');
    }
    const summary = document.getElementById('one-click-status');
    if (summary && !document.getElementById('one-click-conn-alert')) {
      const alert = document.createElement('div');
      alert.id = 'one-click-conn-alert';
      alert.className = 'one-click-conn-alert';
      alert.textContent = `与服务器失去连接（已连续失败 ${STATE.failCount} 次），正在自动重试。若刚重启过服务请稍候，或手动刷新页面。`;
      summary.prepend(alert);
    }
  }

  function refreshStatusSilently() {
    // [轮询自愈 20260904] 页面隐藏时定时器已被浏览器节流；tick 若仍触发，
    // 只保留少量心跳请求检测任务终态，其余主动让路。回到前台立即恢复全量轮询。
    if (document.hidden && STATE.hiddenSkip < POLL_MAX_HIDDEN_SKIP) {
      STATE.hiddenSkip += 1;
      return;
    }
    if (!document.hidden) STATE.hiddenSkip = 0;
    refreshStatus().catch(() => {
      // [轮询自愈 20260904] 失败不再完全静默：递增连续失败计数，
      // 达到阈值后给出明确连接提示；恢复成功由 refreshStatus 自动复位。
      STATE.failCount += 1;
      renderConnectionAlert();
    });
  }

  async function startOneClick(mode = 'resume') {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    await refreshStatus();
    const confirmed = window.confirm(mode === 'restart'
      ? '将从预检查开始重跑自动流程。已锁定的 Mask 和人工旁白仍会保护，但分镜、图片和音频可能重新生成。继续？'
      : '将重新检查上游产物，自动从最早失效阶段继续，并保护人工 Mask、旁白和未过期产物。继续？');
    if (!confirmed) return;
    const button = document.getElementById(mode === 'restart' ? 'btn-one-click-restart' : 'btn-one-click-start');
    const original = button?.textContent || '智能继续';
    if (button) {
      button.disabled = true;
      button.textContent = '启动中...';
    }
    try {
      const result = await apiPost(`/api/projects/${encodeURIComponent(projectId)}/one-click-generate`, { mode });
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
    // [轮询自愈 20260904] 浏览器会把后台标签页的定时器节流到分钟级，切回
    // 前台时屏幕上的状态可能已滞后数分钟。页面重新可见时立即补一次刷新，
    // 不等下一个轮询 tick；连接已断开时也会立刻尝试并进入失败计数。
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      if (STATE.polling && activeProjectId()) refreshStatusSilently();
    });
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
