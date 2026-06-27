(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_visual_draft_quality_project_id') || '',
    loading: false,
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

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  function pct(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return '0.0%';
    return `${(number * 100).toFixed(1)}%`;
  }

  function rememberProjectId(projectId) {
    if (!projectId) return;
    STATE.projectId = String(projectId);
    sessionStorage.setItem('ppt_visual_draft_quality_project_id', STATE.projectId);
  }

  function inferProjectIdFromPage() {
    const urls = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const match = urls.match(/\/api\/projects\/([^/]+)\//);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function activeProjectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) rememberProjectId(fromWindow);
    const inferred = inferProjectIdFromPage();
    if (inferred) rememberProjectId(inferred);
    return STATE.projectId || sessionStorage.getItem('ppt_visual_draft_quality_project_id') || inferred || '';
  }

  function qualityUrl(projectId) {
    return `/api/projects/${encodeURIComponent(projectId)}/steps/3/visual-draft-quality`;
  }

  function ensureStyle() {
    if (document.getElementById('visual-draft-quality-style')) return;
    const style = document.createElement('style');
    style.id = 'visual-draft-quality-style';
    style.textContent = `
      #step3-btn-visual-draft-quality { font-size: .85rem; padding: .35rem .9rem; }
      .visual-quality-modal { max-width: 1050px; width: min(1050px, 94vw); }
      .visual-quality-note { color: #555; line-height: 1.55; margin: .45rem 0 .85rem; }
      .visual-quality-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; margin: .85rem 0 1rem; }
      .visual-quality-kpi { border: 2px solid #111; border-radius: 12px; padding: .75rem; background: #fffef9; box-shadow: 2px 2px 0 rgba(0,0,0,.1); }
      .visual-quality-kpi strong { display: block; font-size: 1.25rem; }
      .visual-quality-kpi span { color: #555; font-size: .86rem; }
      .visual-quality-toolbar { display: flex; gap: .6rem; flex-wrap: wrap; margin: .8rem 0; align-items: center; }
      .visual-quality-list { display: grid; gap: .7rem; max-height: 55vh; overflow: auto; padding-right: .25rem; }
      .visual-quality-card { border: 2px solid #111; border-radius: 14px; padding: .8rem; background: #fff; box-shadow: 3px 3px 0 rgba(0,0,0,.1); }
      .visual-quality-card.ok { background: #f4fff4; }
      .visual-quality-card.fail { background: #fff7f2; }
      .visual-quality-card h4 { margin: 0 0 .45rem; display: flex; justify-content: space-between; gap: .7rem; align-items: center; }
      .visual-quality-badge { border: 1.5px solid #111; border-radius: 999px; padding: .12rem .55rem; font-size: .78rem; background: #fff; white-space: nowrap; }
      .visual-quality-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .45rem; margin: .5rem 0; }
      .visual-quality-metric { border: 1px dashed #999; border-radius: 9px; padding: .45rem; font-size: .82rem; background: rgba(255,255,255,.75); }
      .visual-quality-metric strong { display: block; font-size: .95rem; }
      .visual-quality-issues { margin: .5rem 0 0; padding-left: 1.1rem; color: #8a2b00; line-height: 1.45; }
      .visual-quality-empty { border: 2px dashed #111; border-radius: 14px; padding: 1rem; color: #555; background: #fff; }
      @media (max-width: 900px) { .visual-quality-summary, .visual-quality-metrics { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById('modal-visual-draft-quality')) return;
    const modal = document.createElement('div');
    modal.id = 'modal-visual-draft-quality';
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content visual-quality-modal">
        <h3 class="highlight-title">Step 3 图片质量检查</h3>
        <p class="visual-quality-note">检查当前项目所有 <code>visual_draft.png</code> 是否适合后续 Step 5 Mask：尺寸应为 1920×1080，背景应保持纯白，边界应干净，字幕安全区不应被大面积占用。</p>
        <div id="visual-quality-summary" class="visual-quality-summary"></div>
        <div class="visual-quality-toolbar">
          <button id="btn-visual-quality-run" class="primary" type="button">重新检查</button>
          <button id="btn-visual-quality-close" class="secondary" type="button">关闭</button>
        </div>
        <div id="visual-quality-results" class="visual-quality-list">
          <div class="visual-quality-empty">尚未检查。</div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-visual-quality-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-visual-quality-run')?.addEventListener('click', () => runQualityCheck().catch(error => renderError(error)));
  }

  function renderSummary(report) {
    const summary = document.getElementById('visual-quality-summary');
    if (!summary) return;
    if (!report) {
      summary.innerHTML = '';
      return;
    }
    const passCount = Math.max(0, Number(report.checked_count || 0) - Number(report.failed_count || 0));
    summary.innerHTML = `
      <div class="visual-quality-kpi"><strong>${esc(report.checked_count || 0)}</strong><span>已检查图片</span></div>
      <div class="visual-quality-kpi"><strong>${esc(passCount)}</strong><span>通过</span></div>
      <div class="visual-quality-kpi"><strong>${esc(report.failed_count || 0)}</strong><span>需要处理</span></div>
    `;
  }

  function renderResults(report) {
    const container = document.getElementById('visual-quality-results');
    if (!container) return;
    if (!report?.success && report?.error) {
      container.innerHTML = `<div class="visual-quality-empty">检查失败：${esc(report.error)}</div>`;
      renderSummary(report);
      return;
    }
    const results = Array.isArray(report?.results) ? report.results : [];
    renderSummary(report);
    if (!results.length) {
      container.innerHTML = '<div class="visual-quality-empty">没有找到 visual_draft.png。请先完成 Step 3 图片生成。</div>';
      return;
    }
    container.innerHTML = results.map(item => {
      const issues = Array.isArray(item.issues) ? item.issues : [];
      const status = issues.length ? 'fail' : 'ok';
      const slide = String(item.path || '').split(/[\\/]/).slice(-2, -1)[0] || 'unknown slide';
      const size = Array.isArray(item.size) ? item.size.join('×') : '未知';
      const issueHtml = issues.length
        ? `<ul class="visual-quality-issues">${issues.map(issue => `<li>${esc(issue)}</li>`).join('')}</ul>`
        : '<p class="visual-quality-note">白底质量看起来可接受。</p>';
      return `
        <article class="visual-quality-card ${status}">
          <h4><span>${esc(slide)}</span><span class="visual-quality-badge">${issues.length ? '需要处理' : '通过'}</span></h4>
          <div class="visual-quality-metrics">
            <div class="visual-quality-metric"><strong>${esc(size)}</strong><span>尺寸</span></div>
            <div class="visual-quality-metric"><strong>${pct(item.non_white_ratio)}</strong><span>非白区域</span></div>
            <div class="visual-quality-metric"><strong>${pct(item.border_non_white_ratio)}</strong><span>边界非白</span></div>
            <div class="visual-quality-metric"><strong>${pct(item.subtitle_safe_non_white_ratio)}</strong><span>字幕区占用</span></div>
          </div>
          ${issueHtml}
        </article>
      `;
    }).join('');
  }

  function renderError(error) {
    const container = document.getElementById('visual-quality-results');
    if (container) container.innerHTML = `<div class="visual-quality-empty">检查失败：${esc(error.message || error)}</div>`;
    renderSummary(null);
    toast(`图片质量检查失败：${error.message || error}`, 6000);
  }

  async function runQualityCheck() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('未找到当前项目，请先进入项目工作区。');
    const button = document.getElementById('btn-visual-quality-run');
    const container = document.getElementById('visual-quality-results');
    if (STATE.loading) return;
    STATE.loading = true;
    if (button) button.disabled = true;
    if (container) container.innerHTML = '<div class="visual-quality-empty">正在检查 Step 3 图片质量...</div>';
    try {
      const report = await apiGet(qualityUrl(projectId));
      renderResults(report);
      if (report.success) toast(`图片质量检查完成：${report.failed_count || 0} 张需要处理`, 3500);
      else toast('图片质量检查未通过，请查看结果。', 4500);
    } finally {
      STATE.loading = false;
      if (button) button.disabled = false;
    }
  }

  function openModal() {
    ensureStyle();
    ensureModal();
    const modal = document.getElementById('modal-visual-draft-quality');
    if (modal) modal.style.display = 'block';
    runQualityCheck().catch(error => renderError(error));
  }

  function closeModal() {
    const modal = document.getElementById('modal-visual-draft-quality');
    if (modal) modal.style.display = 'none';
  }

  function ensureStep3Button() {
    ensureStyle();
    ensureModal();
    const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!toolbar || document.getElementById('step3-btn-visual-draft-quality')) return;
    const button = document.createElement('button');
    button.id = 'step3-btn-visual-draft-quality';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '图片质量检查';
    button.title = '检查 Step 3 visual_draft.png 是否保持纯白底、尺寸正确、适合 Step 5 Mask';
    button.addEventListener('click', openModal);
    const imageStyleButton = document.getElementById('step3-btn-image-style-panel');
    if (imageStyleButton?.parentElement === toolbar) toolbar.insertBefore(button, imageStyleButton.nextSibling);
    else {
      const confirmButton = document.getElementById('step3-btn-confirm');
      if (confirmButton?.parentElement === toolbar) toolbar.insertBefore(button, confirmButton);
      else toolbar.appendChild(button);
    }
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__visualQualityPatched) {
        const originalEnter = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await originalEnter.apply(this, arguments);
          ensureStep3Button();
          return result;
        };
        window.enterWorkspace.__visualQualityPatched = true;
      }
      if (window.exitWorkspace && !window.exitWorkspace.__visualQualityPatched) {
        const originalExit = window.exitWorkspace;
        window.exitWorkspace = function patchedExitWorkspace() {
          STATE.projectId = '';
          sessionStorage.removeItem('ppt_visual_draft_quality_project_id');
          return originalExit.apply(this, arguments);
        };
        window.exitWorkspace.__visualQualityPatched = true;
      }
    };
    patch();
    const timer = setInterval(() => {
      patch();
      ensureStep3Button();
      if (window.enterWorkspace?.__visualQualityPatched && document.getElementById('step3-btn-visual-draft-quality')) clearInterval(timer);
    }, 500);
  }

  document.addEventListener('DOMContentLoaded', () => {
    patchWorkspaceNavigation();
    ensureStep3Button();
  });
})();
