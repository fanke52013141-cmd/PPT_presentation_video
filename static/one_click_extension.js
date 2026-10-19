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
    // [全自动直启 20260908] 会话内已自动触发过续跑的项目集合与进行中标记：
    // 每个项目每次页面会话只自动触发一次，避免固定失败被反复重跑。
    autoTriggered: new Set(),
    autoStarting: false,
    pauseRequestInFlight: false,
    pauseRequested: false,
    lastStatus: null,
  };

  // [轮询自愈 20260904] 连续失败达到该阈值（约 7.5 秒无响应）才展示连接
  // 中断提示：瞬时网络抖动（1~2 次）不打扰用户，服务重启期间明确告知
  // "正在自动重试"，避免画面停留在旧状态被误读为流程卡住。
  const POLL_FAIL_ALERT_THRESHOLD = 3;
  // [轮询自愈 20260904] 页面隐藏时保留的轮询心跳上限：浏览器对后台标签页
  // 的定时器有分钟级节流，若 tick 仍被触发则以少量心跳检测任务终态。
  const POLL_MAX_HIDDEN_SKIP = 4;

  // [自动模式跟随 20260813] 后端 stage id -> 左侧菜单 data-step 映射。
  // annotation/digital_human 阶段此前缺失映射:运行进入这两个阶段时
  // stepper 既无"进行中"标记也不自动跟随,用户会误以为流程卡在 TTS。
  const STAGE_TO_STEP = {
    preflight: 1,
    storyboard: 2,
    images: 3,
    confirm_images: 3,
    ai_mask: 5,
    narration: 6,
    tts: 6,
    annotation: 10,
    digital_human: 9,
    render: 8,
  };
  const STAGE_LABELS = {
    preflight: '1 导入文章 · 预检查',
    storyboard: '2 分镜规划',
    images: '3 图片生成',
    confirm_images: '3 图片生成 · 确认整页场景',
    ai_mask: '4 AI Mask 标注',
    narration: '5 旁白与音频 · 演讲稿',
    tts: '5 旁白与音频 · 语音合成',
    render: '8 作品输出 · 渲染视频',
  };
  const STATUS_LABELS = {
    idle: '未开始',
    running: '进行中',
    completed: '已完成',
    done: '已完成',
    failed: '需要处理',
    paused: '已暂停',
    cancelled: '已取消',
    pending: '待处理',
    success: '已完成',
  };

  function stageLabel(value) {
    return STAGE_LABELS[value] || value || '准备中';
  }

  function statusLabel(value) {
    return STATUS_LABELS[value] || value || '未开始';
  }

  function apiGet(url, options = {}) {
    return window.API.get(url, options);
  }

  function apiPost(url, body) {
    return window.API.post(url, body || {});
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  const esc = value => window.escHtml(String(value ?? ''));

  // 一键生成的进度就是工作区的主叙事。每次后端进入一个新的阶段，都把
  // 左侧高亮和内容面板切到相应步骤；lastFollowedStage 保证轮询不会反复
  // 重载同一个面板。
  function followActiveStage(status) {
    const runState = (status && status.status) || 'idle';
    if (runState !== 'running') {
      STATE.lastFollowedStage = '';
      return;
    }
    const stage = (status && status.current_stage) || '';
    if (!stage || stage === STATE.lastFollowedStage) return;
    STATE.lastFollowedStage = stage;
    const targetStep = STAGE_TO_STEP[stage];
    if (targetStep && typeof window.navigateToStep === 'function') {
      Promise.resolve(window.navigateToStep(targetStep)).catch(() => {
        // 导航失败不阻断状态轮询；下一次阶段切换或手动点击仍可恢复。
      });
    } else if (typeof window.refreshCurrentProjectStatus === 'function') {
      try { window.refreshCurrentProjectStatus(); } catch (e) { /* 刷新失败不阻断轮询 */ }
    }
  }

  function formatElapsedSeconds(value) {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return hours > 0
      ? `${hours}小时${minutes}分${remainder}秒`
      : `${minutes}分${remainder}秒`;
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
          // [全自动直启 20260908] 进入项目后读取一次状态；全自动模式下若
          // 流程尚未开始或上次失败待处理，直接自动续跑，无需再手动点击
          // "一键生成"。其余状态保持原有静默刷新行为。
          enterStatusAndMaybeAutoStart();
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
        <div class="prompt-title-row">
          <h3 class="highlight-title">一键生成视频</h3>
          <button id="btn-one-click-close-icon" class="icon-button" type="button" aria-label="关闭">×</button>
        </div>
        <div id="one-click-status" class="one-click-status-line">尚未读取状态。</div>
        <div id="one-click-stages" class="one-click-stage-list"></div>
        <div class="one-click-toolbar">
          <button id="btn-one-click-start" class="success" type="button">智能继续</button>
          <button id="btn-one-click-restart" class="secondary" type="button">从头重跑</button>
          <button id="btn-one-click-pause" class="secondary" type="button" hidden>暂停生成</button>
          <button id="btn-one-click-refresh" class="secondary" type="button">刷新状态</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-one-click-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-one-click-close-icon')?.addEventListener('click', closeModal);
    document.getElementById('btn-one-click-refresh')?.addEventListener('click', () => refreshStatus().catch(error => toast(`刷新失败：${error.message}`, 6000)));
    document.getElementById('btn-one-click-start')?.addEventListener('click', () => startOneClick('resume').catch(error => toast(`启动失败：${error.message}`, 6000)));
    document.getElementById('btn-one-click-restart')?.addEventListener('click', () => startOneClick('restart').catch(error => toast(`启动失败：${error.message}`, 6000)));
    document.getElementById('btn-one-click-pause')?.addEventListener('click', () => pauseOneClick().catch(error => toast(`暂停失败：${error.message}`, 6000)));
  }

  function ensureEntryButton() {
    ensureModal();
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar || document.getElementById('btn-one-click-generate')) return;
    const entry = document.createElement('div');
    entry.className = 'one-click-sidebar-entry';
    const button = document.createElement('button');
    button.id = 'btn-one-click-generate';
    button.className = 'success';
    button.type = 'button';
    button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.2 8.8L21 11L14.2 13.2L12 20L9.8 13.2L3 11L9.8 8.8L12 2Z"></path><path d="M19 17L19.8 19.2L22 20L19.8 20.8L19 23L18.2 20.8L16 20L18.2 19.2L19 17Z" opacity="0.8"></path></svg><span>一键生成视频</span>';
    button.addEventListener('click', () => openModal().catch(error => toast(`打开失败：${error.message}`, 6000)));
    entry.appendChild(button);
    sidebar.appendChild(entry);
  }

  let panelRefreshInFlight = false;
  let previousPanelStage = '';
  let oneClickContentStage = '';
  async function syncLivePanel(status) {
    window.syncStoryboardGenerationState?.(status);
    const contentStage = status?.status === 'running' ? status?.current_stage : '';
    if (contentStage === 'ai_mask' || oneClickContentStage === 'ai_mask') {
      renderPageTaskState(document.getElementById('step-panel-5'), 'mask', contentStage === 'ai_mask' ? 'running' : status?.status === 'failed' ? 'error' : 'done', contentStage === 'ai_mask' ? '正在关联画面元素与演讲稿，生成 AI Mask 标注' : status?.status === 'failed' ? 'AI Mask 标注失败' : 'AI Mask 标注已完成', 'image');
    }
    if (contentStage === 'render' || oneClickContentStage === 'render') {
      renderPageTaskState(document.getElementById('step-panel-8'), 'one-click-output', contentStage === 'render' ? 'running' : status?.status === 'completed' ? 'done' : 'error', contentStage === 'render' ? '正在生成作品视频' : status?.status === 'completed' ? '作品视频生成完成' : '作品生成已停止', 'video');
    }
    oneClickContentStage = contentStage;

    if (panelRefreshInFlight) return;
    const runtimeState = window.PPTStudio?.runtime?.state;
    if (!runtimeState?.currentProject || runtimeState.currentProject.id !== activeProjectId()) return;
    const stage = status?.current_stage || '';
    const previous = previousPanelStage;
    previousPanelStage = stage;
    panelRefreshInFlight = true;
    try {
      // Refresh artifacts in the visible panel; never rebuild narration editors
      // while the user is typing. Existing loaders guard project/session races.
      if (runtimeState.currentStep === 3 && ['images', 'confirm_images'].includes(stage)) await window.refreshStep3Images?.();
      if (runtimeState.currentStep === 6 && stage === 'tts') await window.loadStep7Data?.();
      if (previous === 'storyboard' && stage !== 'storyboard' && runtimeState.currentStep === 2) await window.loadStep2Data?.();
      if (previous === 'tts' && stage !== 'tts' && runtimeState.currentStep === 6) await window.loadStep7Data?.();
    } catch (error) {
      console.warn('Live generation presentation refresh failed', error);
    } finally {
      panelRefreshInFlight = false;
    }
  }

  function renderStatus(status) {
    const summary = document.getElementById('one-click-status');
    const stages = document.getElementById('one-click-stages');
    if (!summary || !stages) return;
    const state = status?.status || 'idle';
    const current = status?.current_stage || '';
    STATE.lastStatus = status || {};
    if (state !== 'running') STATE.pauseRequested = false;
    const pauseButton = document.getElementById('btn-one-click-pause');
    if (pauseButton) {
      pauseButton.hidden = state !== 'running';
      pauseButton.disabled = state !== 'running' || STATE.pauseRequestInFlight || STATE.pauseRequested;
      pauseButton.textContent = STATE.pauseRequested ? '正在暂停…' : '暂停生成';
    }
    // [轮询自愈 20260904] 本地数据新鲜度：running 态下轮询每 2.5 秒重渲染，
    // 该数字会持续滚动；切后台导致的滞后一眼可辨。
    const freshNote = STATE.lastRefreshAt
      ? `页面数据刷新于 ${Math.max(0, Math.round((Date.now() - STATE.lastRefreshAt) / 1000))} 秒前`
      : '';
    const activity = document.getElementById('project-activity-status');
    if (activity) {
      const currentStage = (status?.stages || []).find(stage => stage.id === current);
      const message = currentStage?.title || stageLabel(current) || currentStage?.message || '';
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
      <strong>状态：</strong><span class="one-click-pill ${esc(state)}">${esc(statusLabel(state))}</span>
      ${current ? `<span style="margin-left:.5rem;">当前阶段：${esc(stageLabel(current))}</span>` : ''}
      ${state === 'running' ? '<br><small>系统会复用已完成且仍有效的产物；你可以继续查看已解锁步骤。</small>' : ''}
      ${status?.run_started_at || status?.started_at ? `<br><small>本次开始：${esc(status.run_started_at || status.started_at)}　${state === 'running' ? '已用' : '总耗时'}：${esc(formatElapsedSeconds(status.run_elapsed_seconds))}</small>` : ''}
      ${status?.run_finished_at ? `<br><small>本次结束：${esc(status.run_finished_at)}</small>` : ''}
      ${freshNote ? `<br><small>${freshNote}</small>` : ''}
      ${status?.video?.url ? `<br><a href="${esc(status.video.url)}" target="_blank">打开生成视频</a>` : ''}
    `;
    const list = Array.isArray(status?.stages) ? status.stages : [];
    const visibleStages = [
      ['1 导入文章', ['preflight']], ['2 分镜规划', ['storyboard']],
      ['3 图片生成', ['images', 'confirm_images']], ['4 AI 标注', ['ai_mask']],
      ['5 旁白与音频', ['narration', 'tts']], ['6 勾画标注', ['annotation']],
      ['7 数字人讲解', ['digital_human']], ['8 作品输出', ['render']],
    ];
    const renderReached = list.some(item => item.id === 'render' && item.status !== 'pending');
    const copiedErrors = [];
    stages.innerHTML = visibleStages.map(([title, ids], index) => {
      const members = list.filter(item => ids.includes(item.id));
      const finished = item => ['done', 'completed', 'success', 'skipped'].includes(item.status);
      let cardStatus = 'pending';
      if (members.some(item => item.status === 'failed')) cardStatus = 'failed';
      else if (members.some(item => item.status === 'running')) cardStatus = state === 'paused' ? 'paused' : 'running';
      else if (members.some(item => item.status === 'paused')) cardStatus = 'paused';
      else if (members.length && ids.every(id => members.some(item => item.id === id && finished(item)))) cardStatus = 'done';
      else if (!members.length && index >= 5 && index <= 6 && renderReached) cardStatus = 'done';
      const errors = members.flatMap(item => item.blocking_errors?.length ? item.blocking_errors : item.status === 'failed' && item.message ? [item.message] : []);
      const active = members.find(item => item.status === 'running' || item.status === 'failed') || members[members.length - 1];
      const message = errors.length ? `错误：${errors.join(' / ')}` : cardStatus === 'done' ? '' : cardStatus === 'paused' ? '' : active?.message || '';
      copiedErrors[index] = message;
      return `<article class="one-click-stage"><strong>${esc(title)}<span class="one-click-pill ${esc(cardStatus)}">${esc(statusLabel(cardStatus))}</span></strong>
        ${errors.length ? `<button type="button" class="one-click-stage-message" data-copy-error="${index}" aria-label="复制完整错误">${esc(message)}</button>` : `<small class="one-click-stage-message">${esc(message)}</small>`}</article>`;
    }).join('');
    stages.querySelectorAll('[data-copy-error]').forEach(button => {
      button.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(copiedErrors[Number(button.dataset.copyError)]);
          toast('错误已复制');
        } catch (_) { toast('复制失败，请检查浏览器剪贴板权限'); }
      });
    });
    // 阶段变化时同步切换左侧 Tab 和对应内容面板。
    followActiveStage(status);
    // [一键进度同步 20260912] 无论面板停在哪里，左侧步骤条都实时挂上
    // 当前阶段的"进行中"标记；一键结束/失败/暂停后清除。
    const runStateNow = (status && status.status) || 'idle';
    if (runStateNow !== 'running') {
      if (window.markStepperRunningStep) window.markStepperRunningStep(null, '');
    } else {
      const stageNow = (status && status.current_stage) || '';
      const runningTargetStep = STAGE_TO_STEP[stageNow];
      if (runningTargetStep && window.markStepperRunningStep) {
        window.markStepperRunningStep(runningTargetStep, stageLabel(stageNow));
      }
    }
    // [一键进度出口 20260904] 面板内注入当前阶段进度横幅
    renderStageProgressInPanel(status);
    void syncLivePanel(status);
  }

  async function refreshStatus() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目，请先进入项目工作区。');
    const result = await apiGet(`/api/projects/${encodeURIComponent(projectId)}/one-click-generate/status`, { silent: true });
    // [一键进度同步 20260912] 切换项目后重置阶段跟随去重，让新项目的
    // 运行阶段在首次轮询时就能把左侧步骤带到正确位置，而不是停留在
    // 上一个项目遗留的最后跟随阶段。
    if (STATE.lastPolledProject !== projectId) {
      STATE.lastPolledProject = projectId;
      STATE.lastFollowedStage = '';
    }
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

  // [全自动直启 20260908] 允许全自动模式进入项目时直接续跑的状态集合：
  // idle = 尚未开始；failed = 上次运行失败待处理。paused/cancelled 是用户
  // 显式暂停或取消的结果，保持手动；waiting_for_review/waiting_for_user
  // 需要用户审查或输入；completed 已完成不重跑。
  const AUTO_TRIGGER_STATUSES = new Set(['idle', 'failed']);

  // [全自动直启 20260908] 进入项目时读取一键状态并在满足条件时自动续跑：
  // 条件为全自动模式（body.mode-auto 由 applyProjectAiMode 维护）且状态
  // 属于 AUTO_TRIGGER_STATUSES 且本会话未触发过。任何失败都只提示一次，
  // 不打断进入项目的正常流程。
  async function enterStatusAndMaybeAutoStart() {
    let status = null;
    try {
      status = await refreshStatus();
    } catch (error) {
      STATE.failCount += 1;
      renderConnectionAlert();
      return;
    }
    const projectId = activeProjectId();
    if (!projectId || !AUTO_TRIGGER_STATUSES.has((status && status.status) || 'idle')) return;
    if (!document.body.classList.contains('mode-auto')) return;
    if (STATE.autoStarting || STATE.autoTriggered.has(projectId)) return;
    await autoStartOneClick();
  }

  // [全自动直启 20260908] 静默启动一键生成（绕过手动模式的确认弹窗）：
  // 全自动模式本身已声明连续执行意图，resume 语义会自动从最早失效阶段
  // 续跑并保护人工 Mask、旁白和未过期产物。
  async function autoStartOneClick() {
    const projectId = activeProjectId();
    if (!projectId) return;
    STATE.autoStarting = true;
    STATE.autoTriggered.add(projectId);
    try {
      const result = await apiPost(`/api/projects/${encodeURIComponent(projectId)}/one-click-generate`, { mode: 'resume' });
      renderStatus(result.status || {});
      toast(result.already_running ? '一键生成正在运行。' : '全自动模式：已自动继续生成流程。', 4000);
      startPolling();
    } catch (error) {
      toast(`自动继续失败：${error.message}，可点击左侧"一键生成"重试。`, 6000);
    } finally {
      STATE.autoStarting = false;
    }
  }

  async function startOneClick(mode = 'resume') {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    await refreshStatus();
    const confirmed = await window.confirmAction('启动自动生成', mode === 'restart'
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
      if (window.state?.currentProject) {
        Object.assign(window.state.currentProject, { production_mode: 'one_click', presentation_mode: 'full_frame', mask_enabled: false });
        window.renderProductionModeSummary?.();
      }
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

  async function pauseOneClick() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    if (STATE.pauseRequestInFlight || STATE.pauseRequested) return;
    STATE.pauseRequestInFlight = true;
    renderStatus(STATE.lastStatus || { status: 'running' });
    try {
      const result = await apiPost(`/api/projects/${encodeURIComponent(projectId)}/one-click-pause`);
      STATE.pauseRequested = result.pause_requested === true;
      renderStatus(result.status || STATE.lastStatus || { status: 'running' });
      toast(STATE.pauseRequested ? '已请求暂停；当前阶段安全完成后会暂停。' : '自动生成已暂停。', 4000);
      startPolling();
    } finally {
      STATE.pauseRequestInFlight = false;
      renderStatus(STATE.lastStatus || { status: 'running' });
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

  let booted = false;
  function boot() {
    if (booted) return;
    booted = true;
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
