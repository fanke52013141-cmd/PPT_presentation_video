(function () {
  'use strict';

  const MODAL_ID = 'modal-ai-mask-settings';
  const USER_SETTING_KEYS = new Set([
    'white_threshold',
    'color_tolerance',
    'min_element_area',
    'component_padding_px'
  ]);

  const PARAMS = [
    {
      key: 'white_threshold', label: '白底识别阈值', type: 'number', default: 245, min: 220, max: 255, step: 1,
      usual: '235 - 252',
      help: '判断哪些像素算白色背景。背景灰、白边残留多就调低；浅色元素被误删就调高。'
    },
    {
      key: 'color_tolerance', label: '白色色差容忍', type: 'number', default: 12, min: 0, max: 40, step: 1,
      usual: '5 - 24',
      help: '允许白色像素有轻微偏黄、偏蓝。白底有色偏就调高；浅色彩色元素被当背景删掉就调低。'
    },
    {
      key: 'min_element_area', label: '最小元素面积', type: 'number', default: 120, min: 10, max: 10000, step: 10,
      usual: '20 - 800',
      help: '小于这个面积的连通块会当噪点过滤。噪点太多调高；小图标、标点、小字被漏掉调低。'
    },
    {
      key: 'component_padding_px', label: 'AI 看图框外扩', type: 'number', default: 12, min: 0, max: 80, step: 1,
      usual: '4 - 32 px',
      help: '只扩大提供给多模态模型的候选框上下文，不修改最终精确 Mask 像素。模型看不清元素周边关系时调高；候选框过度遮挡时调低。'
    }
  ];

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function apiPut(url, body) {
    return window.API?.put ? window.API.put(url, body) : fetch(url, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function apiPost(url, body) {
    return window.API?.post ? window.API.post(url, body) : fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function toast(msg, duration) {
    if (window.showToast) window.showToast(msg, duration || 3000);
    else console.log(msg);
  }

  function projectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) return fromWindow;
    const bgSrc = document.getElementById('step5-bg-img')?.getAttribute('src') || '';
    const match = bgSrc.match(/\/api\/projects\/([^/]+)\/slides\//);
    if (match) return decodeURIComponent(match[1]);
    const currentLinks = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const anyMatch = currentLinks.match(/\/api\/projects\/([^/]+)\//);
    return anyMatch ? decodeURIComponent(anyMatch[1]) : null;
  }

  function escapeAttr(value) {
    return String(value ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }


  function fitFullscreenCanvas() {
    const container = document.getElementById('canvas-container');
    if (!container) return;
    if (!document.body.classList.contains('step5-fullscreen-mode')) {
      container.style.width = '';
      container.style.height = '';
      return;
    }
    const left = container.closest('.workspace-left') || container.parentElement;
    const rect = left?.getBoundingClientRect?.();
    const maxW = Math.max(240, (rect?.width || window.innerWidth) - 12);
    const maxH = Math.max(135, (rect?.height || window.innerHeight) - 12);
    let width = maxW;
    let height = width * 9 / 16;
    if (height > maxH) {
      height = maxH;
      width = height * 16 / 9;
    }
    container.style.width = `${Math.floor(width)}px`;
    container.style.height = `${Math.floor(height)}px`;
  }

  function installFullscreenFitWatch() {
    if (window.__aiMaskFullscreenFitWatch) return;
    window.__aiMaskFullscreenFitWatch = true;
    window.addEventListener('resize', fitFullscreenCanvas);
    const observer = new MutationObserver(fitFullscreenCanvas);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    setInterval(fitFullscreenCanvas, 800);
  }

  function button(id, text, cls) {
    const b = document.createElement('button');
    b.id = id;
    b.type = 'button';
    b.className = cls || 'secondary';
    b.textContent = text;
    return b;
  }

  function injectButtons() {
    const toolbar = document.querySelector('#step-panel-5 .step5-toolbar');
    if (!toolbar) return;
    ensureInlineStatus();
    ensureReviewPanel();
    ensurePreviewControls();
    if (document.getElementById('step5-btn-ai-mask')) return;
    const settings = button('step5-btn-ai-mask-settings', 'AI 标注设置', 'secondary');
    const run = button('step5-btn-ai-mask', '重新运行 AI 标注', 'secondary');
    const anchor = document.getElementById('step5-btn-fullscreen');
    toolbar.insertBefore(settings, anchor || null);
    toolbar.insertBefore(run, anchor || null);
    settings.addEventListener('click', openSettings);
    run.addEventListener('click', runAnnotation);
  }

  function ensurePreviewControls() {
    let controls = document.getElementById('ai-mask-preview-modes');
    if (controls) return controls;
    const toolbar = document.querySelector('#step-panel-5 .step5-toolbar');
    if (!toolbar) return null;
    controls = document.createElement('div');
    controls.id = 'ai-mask-preview-modes';
    controls.className = 'ai-mask-preview-modes';
    controls.setAttribute('aria-label', 'Mask 预览模式');
    controls.innerHTML = `
      <button type="button" data-preview-mode="source">原图</button>
      <button type="button" data-preview-mode="mask" class="active">标注范围</button>
      <button type="button" data-preview-mode="final" title="使用生产抠图算法构建当前页">最终抠图</button>`;
    const anchor = document.getElementById('step5-btn-fullscreen');
    toolbar.insertBefore(controls, anchor || null);
    controls.querySelector('[data-preview-mode="source"]')?.addEventListener('click', () => setPreviewMode('source'));
    controls.querySelector('[data-preview-mode="mask"]')?.addEventListener('click', () => setPreviewMode('mask'));
    controls.querySelector('[data-preview-mode="final"]')?.addEventListener('click', buildExactPreview);
    return controls;
  }

  function updatePreviewControls(mode = 'mask', loading = false) {
    const controls = ensurePreviewControls();
    if (!controls) return;
    controls.querySelectorAll('[data-preview-mode]').forEach(button => {
      button.classList.toggle('active', button.dataset.previewMode === mode);
    });
    const finalButton = controls.querySelector('[data-preview-mode="final"]');
    if (finalButton) {
      finalButton.disabled = loading;
      finalButton.classList.toggle('loading', loading);
      finalButton.textContent = loading ? '构建中…' : '最终抠图';
    }
  }

  function setPreviewMode(mode) {
    if (typeof window.setStep5MaskPreviewMode === 'function') {
      window.setStep5MaskPreviewMode(mode);
    }
    updatePreviewControls(mode, false);
  }

  function installPreviewEvents() {
    if (window.__aiMaskPreviewEventsInstalled) return;
    window.__aiMaskPreviewEventsInstalled = true;
    window.addEventListener('step5-mask-preview-invalidated', () => updatePreviewControls('mask', false));
    window.addEventListener('step5-mask-preview-mode', event => updatePreviewControls(event.detail?.mode || 'mask', false));
  }

  async function buildExactPreview() {
    const id = projectId();
    const slideId = typeof window.getCurrentStep5SlideId === 'function' ? window.getCurrentStep5SlideId() : '';
    if (!id || !slideId) {
      toast('请先打开需要预览的 Mask 页面。', 5000);
      return;
    }
    setPreviewMode('mask');
    updatePreviewControls('mask', true);
    setInlineStatus(`正在构建 ${slideId} 的最终抠图预览...`, true, true);
    try {
      await flushStep5DraftBeforeAiMask();
      const result = await apiPost(
        `/api/projects/${encodeURIComponent(id)}/steps/5/slides/${encodeURIComponent(slideId)}/preview`,
        {},
      );
      const currentSlideId = typeof window.getCurrentStep5SlideId === 'function' ? window.getCurrentStep5SlideId() : '';
      if (currentSlideId !== slideId) {
        setPreviewMode('mask');
        return;
      }
      const loaded = typeof window.setStep5MaskPreviewMode === 'function'
        ? await window.setStep5MaskPreviewMode('final', result.preview_url, slideId)
        : false;
      if (!loaded) throw new Error('预览图片未能加载');
      updatePreviewControls('final', false);
      const removed = Number(result.cutout_stats?.removed_outer_white_pixel_count || 0).toLocaleString();
      toast(`最终抠图预览已生成，移除 ${removed} 个边界连通白底像素。`, 5000);
      setInlineStatus('', false, false);
    } catch (error) {
      setPreviewMode('mask');
      setInlineStatus('最终抠图预览失败', true, false);
      toast(`❌ 最终抠图预览失败：${error.message}`, 7000);
    } finally {
      const mode = document.querySelector('#ai-mask-preview-modes .active')?.dataset.previewMode || 'mask';
      updatePreviewControls(mode, false);
    }
  }

  let reviewIssues = [];
  let reviewIndex = 0;
  let reviewQualityStatus = '';

  function ensureReviewPanel() {
    let panel = document.getElementById('ai-mask-review-panel');
    if (panel) return panel;
    const header = document.querySelector('#step-panel-5 .step5-mask-header');
    const toolbar = document.querySelector('#step-panel-5 .step5-toolbar');
    if (!header && !toolbar) return null;
    panel = document.createElement('div');
    panel.id = 'ai-mask-review-panel';
    panel.className = 'ai-mask-review-panel';
    panel.innerHTML = `
      <div class="ai-mask-review-summary" aria-live="polite"></div>
      <div class="ai-mask-review-actions">
        <button id="ai-mask-review-prev" class="secondary" type="button">上一个问题</button>
        <span id="ai-mask-review-position" class="ai-mask-review-position"></span>
        <button id="ai-mask-review-next" class="secondary" type="button">下一个问题</button>
      </div>`;
    (header || toolbar.parentElement).insertAdjacentElement('afterend', panel);
    panel.querySelector('#ai-mask-review-prev')?.addEventListener('click', () => focusReviewIssue(reviewIndex - 1));
    panel.querySelector('#ai-mask-review-next')?.addEventListener('click', () => focusReviewIssue(reviewIndex + 1));
    return panel;
  }

  function setReviewIssues(issues, qualityStatus = '') {
    reviewIssues = Array.isArray(issues) ? issues.filter(issue => issue && typeof issue === 'object') : [];
    reviewIndex = Math.min(reviewIndex, Math.max(0, reviewIssues.length - 1));
    reviewQualityStatus = String(qualityStatus || (reviewIssues.length ? 'needs_review' : 'passed'));
    window.__aiMaskReviewIssues = reviewIssues;
    renderReviewPanel();
    const stepPanel = document.getElementById('step-panel-5');
    if (stepPanel && typeof window.renderStep5Workspace === 'function' && window.getComputedStyle(stepPanel).display !== 'none') {
      window.renderStep5Workspace();
    }
  }

  function renderReviewPanel() {
    const panel = ensureReviewPanel();
    if (!panel) return;
    const summary = panel.querySelector('.ai-mask-review-summary');
    const position = panel.querySelector('#ai-mask-review-position');
    const hasResult = !!reviewQualityStatus;
    panel.classList.toggle('visible', hasResult);
    panel.classList.toggle('passed', reviewQualityStatus === 'passed');
    panel.classList.toggle('needs-review', reviewQualityStatus === 'needs_review');
    panel.classList.toggle('failed', reviewQualityStatus === 'failed');
    if (!hasResult) return;
    const current = reviewIssues[reviewIndex];
    const blockingCount = reviewIssues.filter(issue => issue.severity === 'blocking').length;
    if (reviewQualityStatus === 'passed') {
      summary.innerHTML = '<strong>AI 标注质量通过</strong><span>前景覆盖、组件归属与像素互斥检查均已通过。</span>';
    } else if (reviewQualityStatus === 'failed') {
      summary.innerHTML = `<strong>AI 标注未生成有效结果</strong><span>${escapeAttr(current?.message || '请检查设置后重新运行。')}</span>`;
    } else {
      summary.innerHTML = `<strong>AI 标注已生成，${reviewIssues.length} 处需要检查${blockingCount ? `（${blockingCount} 处重要）` : ''}</strong><span>${escapeAttr(current?.message || '请逐项复核 Mask 归属。')}</span>`;
    }
    if (position) position.textContent = reviewIssues.length ? `${reviewIndex + 1} / ${reviewIssues.length}` : '0 / 0';
    panel.querySelector('#ai-mask-review-prev').disabled = reviewIssues.length < 2;
    panel.querySelector('#ai-mask-review-next').disabled = reviewIssues.length < 2;
    panel.querySelector('.ai-mask-review-actions').style.display = reviewIssues.length ? 'flex' : 'none';
  }

  function focusReviewIssue(index) {
    if (!reviewIssues.length) return;
    reviewIndex = (index + reviewIssues.length) % reviewIssues.length;
    renderReviewPanel();
    if (typeof window.focusAiMaskIssue === 'function') {
      window.focusAiMaskIssue(reviewIssues[reviewIndex]);
    }
  }

  function ensureInlineStatus() {
    return document.getElementById('project-activity-status');
  }

  function setInlineStatus(message, active = true, spinning = false) {
    const status = ensureInlineStatus();
    if (!status) return;
    status.innerHTML = message
      ? `${spinning ? '<span class="button-spinner"></span>' : ''}<span>${escapeAttr(message)}</span>`
      : '';
    status.classList.toggle('active', !!active && !!message);
    status.classList.toggle('running', !!spinning);
  }

  function inputHtml(def, value) {
    if (def.type === 'boolean') {
      return `<label class="ai-mask-switch"><input class="ai-mask-setting-input" data-key="${def.key}" type="checkbox" ${value ? 'checked' : ''}> 开启</label>`;
    }
    return `<input class="ai-mask-setting-input" data-key="${def.key}" type="number" min="${def.min}" max="${def.max}" step="${def.step}" value="${escapeAttr(value)}">`;
  }

  function paramRow(def, settings) {
    const value = settings[def.key] !== undefined ? settings[def.key] : def.default;
    const rangeLine = `默认：${def.default}\n常用：${def.usual}\n作用：${def.help}`;
    return `
      <div class="ai-mask-param-row">
        <label for="ai-mask-param-${def.key}">${def.label}</label>
        ${inputHtml(def, value).replace('class="ai-mask-setting-input"', `id="ai-mask-param-${def.key}" class="ai-mask-setting-input"`)}
        <span class="ai-mask-help" data-help="${escapeAttr(rangeLine)}">?</span>
      </div>
    `;
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content config-editor-modal" style="max-width:900px;width:min(900px,94vw)">
        <div class="ai-mask-modal-scroll">
          <div class="prompt-title-row">
            <h3 class="highlight-title">AI Mask 自动标注设置</h3>
            <button class="prompt-help-button" type="button" data-prompt-help="ai-mask" aria-label="查看 AI Mask 的输入输出示例">?</button>
          </div>
          <p class="config-editor-note">只保留常用 Mask 参数。大模型匹配参数使用系统默认值；日常只需要调整识别、合并和覆盖策略。</p>
          <div class="ai-mask-section-title"><h4 style="margin:0">Mask 参数</h4><span class="config-editor-note" style="margin:0">悬停问号查看说明</span></div>
          <div id="ai-mask-settings-grid" class="ai-mask-compact-grid"></div>
          <div class="config-editor-note" style="margin-top:.75rem">最终手动抠图固定使用“Mask 边界连通近白色剔除”，保留被内容包围的内部白色，并执行抗锯齿白边去污染。以上白底参数用于自动元素检测。</div>
          <div class="ai-mask-prompt-block">
            <h4>匹配规则提示词</h4>
            <p class="config-editor-note">这里控制“画面元素如何匹配到语块和演讲稿”。可以改方法论；不需要调大模型参数。</p>
            <textarea id="ai-mask-methodology" rows="10" spellcheck="false"></textarea>
          </div>
          <details class="ai-mask-prompt-block">
            <summary style="font-weight:800;cursor:pointer">高级：输出 JSON 结构</summary>
            <p class="config-editor-note">默认不要修改。只有后端解析结构同步调整时才需要改。</p>
            <textarea id="ai-mask-output-structure" rows="8" spellcheck="false"></textarea>
          </details>
          <div class="ai-mask-prompt-block">
            <h4>完整提示词（可直接复制）</h4>
            <textarea id="ai-mask-full-prompt" rows="16" readonly spellcheck="false"></textarea>
          </div>
        </div>
        <div class="config-editor-actions">
          <button id="btn-ai-mask-settings-cancel" class="secondary" type="button">取消</button>
          <button id="btn-ai-mask-settings-save" class="success" type="button">保存设置</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#btn-ai-mask-settings-cancel').addEventListener('click', () => modal.style.display = 'none');
    modal.querySelector('#btn-ai-mask-settings-save').addEventListener('click', saveSettings);
    modal.querySelector('#ai-mask-methodology').addEventListener('input', updateFullPromptPreview);
    modal.querySelector('#ai-mask-output-structure').addEventListener('input', updateFullPromptPreview);
    return modal;
  }

  function composeFullPrompt(methodology, outputStructure) {
    return `${String(methodology || '').trim()}\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n${String(outputStructure || '').trim()}`;
  }

  function updateFullPromptPreview() {
    const modal = ensureModal();
    const target = modal.querySelector('#ai-mask-full-prompt');
    if (!target) return;
    target.value = composeFullPrompt(
      modal.querySelector('#ai-mask-methodology')?.value,
      modal.querySelector('#ai-mask-output-structure')?.value,
    );
  }

  async function openSettings() {
    const modal = ensureModal();
    modal.style.display = 'flex';
    const grid = modal.querySelector('#ai-mask-settings-grid');
    grid.innerHTML = '<div class="card">加载设置中...</div>';
    try {
      const data = await apiGet('/api/settings/ai-mask');
      const settings = data.settings || {};
      grid.innerHTML = PARAMS.map(def => paramRow(def, settings)).join('');
      modal.querySelector('#ai-mask-methodology').value = data.prompts?.methodology || '';
      modal.querySelector('#ai-mask-output-structure').value = data.prompts?.output_structure || '';
      modal.querySelector('#ai-mask-full-prompt').value = data.prompts?.full_prompt || '';
      updateFullPromptPreview();
    } catch (e) {
      grid.innerHTML = `<div class="card">加载失败：${escapeAttr(e.message)}</div>`;
    }
  }

  function collect() {
    const modal = ensureModal();
    const settings = {};
    modal.querySelectorAll('.ai-mask-setting-input').forEach(input => {
      const key = input.dataset.key;
      if (!key || !USER_SETTING_KEYS.has(key)) return;
      if (input.type === 'checkbox') settings[key] = input.checked;
      else if (input.type === 'number') settings[key] = Number(input.value);
      else settings[key] = input.value;
    });
    return {
      settings,
      prompts: {
        methodology: modal.querySelector('#ai-mask-methodology').value,
        output_structure: modal.querySelector('#ai-mask-output-structure').value
      }
    };
  }

  async function saveSettings() {
    const btn = document.getElementById('btn-ai-mask-settings-save');
    btn.disabled = true;
    try {
      await apiPut('/api/settings/ai-mask', collect());
      toast('✅ AI Mask 设置已保存');
      document.getElementById(MODAL_ID).style.display = 'none';
    } catch (e) {
      toast(`❌ 保存失败：${e.message}`, 6000);
    } finally {
      btn.disabled = false;
    }
  }

  async function flushStep5DraftBeforeAiMask() {
    if (window.PPTStudio && typeof window.PPTStudio.flushStep5Draft === 'function') {
      await window.PPTStudio.flushStep5Draft();
      return;
    }
    if (typeof window.saveStep5CurrentState === 'function') {
      window.saveStep5CurrentState();
    }
    if (typeof window.saveStep5Draft === 'function') {
      await window.saveStep5Draft();
    }
  }

  async function runAnnotation(options = {}) {
    const id = projectId();
    if (!id) {
      toast('请先打开项目并进入 Mask 标注页。未能识别当前 project_id。', 6000);
      return;
    }
    const btn = document.getElementById('step5-btn-ai-mask');
    const settingsBtn = document.getElementById('step5-btn-ai-mask-settings');
    const status = ensureInlineStatus();
    btn.disabled = true;
    setPreviewMode('mask');
    if (settingsBtn) settingsBtn.disabled = true;
    setInlineStatus('正在准备 AI 标注...', true, true);
    try {
      await flushStep5DraftBeforeAiMask();
      setInlineStatus('AI 正在关联画面元素与演讲稿...', true, true);
      const result = await apiPost(`/api/projects/${encodeURIComponent(id)}/steps/5/ai-mask/annotate`, {
        scope: 'all_slides',
        settings: {
          overwrite_existing_manual_mask: false,
          skip_locked_groups: true,
        },
      });
      if (result.complete !== true) {
        setReviewIssues(result.review_issues || [], result.quality_status || 'failed');
        throw new Error('仍有画面语块未能完成关联，请重新运行 AI 标注');
      }
      setInlineStatus('', false, false);
      const reviewCount = Number(result.review_issue_count || 0);
      const qualityStatus = String(result.quality_status || (reviewCount ? 'needs_review' : 'passed'));
      if (reviewCount > 0) {
        toast(`AI 标注已完成，有 ${reviewCount} 个位置建议检查。`, 6500);
      } else {
        toast(options.automatic ? 'AI 标注已自动完成。' : 'AI 标注已重新完成。', 4500);
      }
      if (typeof window.loadStep5Data === 'function') await window.loadStep5Data();
      else if (typeof loadStep5Data === 'function') await loadStep5Data();
      setReviewIssues(result.review_issues || [], qualityStatus);
      if (reviewCount > 0) {
        focusReviewIssue(0);
      } else if (typeof window.focusFirstAiMaskResult === 'function') {
        window.focusFirstAiMaskResult();
      }
    } catch (e) {
      setInlineStatus('AI 标注失败', true, false);
      toast(`❌ AI 标注失败：${e.message}`, 8000);
    } finally {
      if (settingsBtn) settingsBtn.disabled = false;
      btn.disabled = false;
      fitFullscreenCanvas();
    }
  }

  const AUTO_ATTEMPTED = new Set();

  async function maybeAutoAnnotate() {
    const panel = document.getElementById('step-panel-5');
    if (!panel || window.getComputedStyle(panel).display === 'none') return;
    const id = projectId();
    if (!id || AUTO_ATTEMPTED.has(id)) return;
    AUTO_ATTEMPTED.add(id);
    try {
      const result = await apiGet(`/api/projects/${encodeURIComponent(id)}/steps/5/result`);
      const annotation = result.manifest?.ai_mask_annotation || {};
      if (['completed', 'completed_needs_review'].includes(annotation.status)) {
        setReviewIssues(annotation.review_issues || [], annotation.quality_status || (annotation.review_required ? 'needs_review' : 'passed'));
        setInlineStatus('', false, false);
        return;
      }
      await runAnnotation({ automatic: true });
    } catch (error) {
      setInlineStatus('AI 标注等待重试', true, false);
    }
  }

  function installAutoAnnotationWatch() {
    if (window.__aiMaskAutoAnnotationWatch) return;
    window.__aiMaskAutoAnnotationWatch = true;
    const panel = document.getElementById('step-panel-5');
    if (!panel) return;
    const observer = new MutationObserver(() => {
      if (window.getComputedStyle(panel).display !== 'none') maybeAutoAnnotate();
    });
    observer.observe(panel, { attributes: true, attributeFilter: ['style', 'class'] });
    maybeAutoAnnotate();
  }

  function boot() {
    installFullscreenFitWatch();
    installPreviewEvents();
    fitFullscreenCanvas();
    injectButtons();
    installAutoAnnotationWatch();
  }

  const timer = setInterval(() => {
    boot();
    if (document.getElementById('step5-btn-ai-mask')) clearInterval(timer);
  }, 500);
  document.addEventListener('DOMContentLoaded', boot);
})();
