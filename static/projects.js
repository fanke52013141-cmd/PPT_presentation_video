// Project library rendering and lifecycle actions.

// Cache of batch automation statuses keyed by project_id.
let _automationStatusMap = {};
let _automationPollTimer = null;
// The image-style template chosen in the create-project modal.
let _selectedStyleTemplate = 'default';

/** Normalise a raw one-click status string to a badge descriptor. */
function _badgeFromStatus(rawStatus) {
  switch (rawStatus) {
    case 'running':          return { cls: 'badge-running',   label: '进行中' };
    case 'waiting_for_user': return { cls: 'badge-waiting',   label: '等待操作' };
    case 'waiting_for_review': return { cls: 'badge-waiting', label: '等待审查' };
    case 'paused':           return { cls: 'badge-paused',    label: '已暂停' };
    case 'failed':           return { cls: 'badge-failed',    label: '出错' };
    case 'completed':        return { cls: 'badge-done',      label: '已完成' };
    default:                 return null;
  }
}

/** Poll batch one-click status and update card badges. */
async function pollAutomationStatus() {
  try {
    const data = await API.get('/api/one-click-statuses');
    if (!data || !data.items) return;
    const map = {};
    data.items.forEach(item => { map[item.project_id] = item; });
    _automationStatusMap = map;

    // Update badges in the DOM.
    document.querySelectorAll('[data-automation-badge]').forEach(el => {
      const pid = el.getAttribute('data-project-id');
      const info = map[pid];
      const badge = info ? _badgeFromStatus(info.status) : null;
      if (badge) {
        el.textContent = badge.label;
        el.className = `automation-badge ${badge.cls}`;
        el.style.display = '';
        el.title = info.current_stage
          ? `当前阶段: ${info.current_stage}`
          : '';
      } else {
        el.style.display = 'none';
      }
    });

    // Continue polling if any project is running or waiting.
    const hasActive = Object.values(map).some(
      item => item.status === 'running' || item.status === 'waiting_for_user'
    );
    if (hasActive) {
      if (!_automationPollTimer) {
        _automationPollTimer = setInterval(pollAutomationStatus, 3000);
      }
    } else if (_automationPollTimer) {
      clearInterval(_automationPollTimer);
      _automationPollTimer = null;
    }
  } catch (_) { /* silent — polling failures are non-fatal */ }
}

/** Pause automation for a project from the card. */
async function pauseAutomationFromCard(projectId) {
  try {
    await API.post(`/api/projects/${projectId}/one-click-pause`);
    showToast('已请求暂停自动化');
    pollAutomationStatus();
  } catch (_) { showToast('暂停失败，请稍后重试'); }
}

/** Resume automation for a project from the card. */
async function resumeAutomationFromCard(projectId) {
  try {
    await API.post(`/api/projects/${projectId}/one-click-generate`, { mode: 'resume' });
    showToast('自动化已继续');
    pollAutomationStatus();
  } catch (_) { showToast('继续失败，请稍后重试'); }
}

/** Load image-style templates into the create-project modal grid. */
async function loadImageStyleTemplates() {
  const grid = document.getElementById('create-style-grid');
  if (!grid) return;
  try {
    const data = await API.get('/api/image-style/templates');
    const templates = (data && data.templates) || [];
    if (templates.length === 0) {
      grid.innerHTML = '<div style="color: var(--muted-color); font-size: 0.85rem; padding: 1rem 0;">暂无可用风格模板</div>';
      return;
    }
    _selectedStyleTemplate = 'default';
    grid.innerHTML = templates.map(t => {
      // references is an object like {"template": {"url": "..."}} not an array
      let thumb = '';
      if (t.references && typeof t.references === 'object') {
        const refKeys = Object.keys(t.references);
        for (const key of refKeys) {
          const ref = t.references[key];
          if (ref && ref.url) { thumb = ref.url; break; }
        }
      }
      const sel = t.id === 'default' ? 'selected' : '';
      return `
        <div class="style-tile ${sel}" data-style-id="${escHtml(t.id)}" style="cursor: pointer; border: 2px solid var(--border-color); border-radius: 8px; overflow: hidden; transition: border-color 0.2s; position: relative;">
          ${thumb
            ? `<img src="${escHtml(thumb)}" alt="${escHtml(t.name)}" style="width: 100%; height: 80px; object-fit: cover; display: block;">`
            : `<div style="width: 100%; height: 80px; background: #f0f0f0; display: flex; align-items: center; justify-content: center; color: #999; font-size: 0.75rem;">无预览</div>`
          }
          <div style="padding: 0.3rem; font-size: 0.8rem; text-align: center; background: #fff;">${escHtml(t.name)}</div>
        </div>`;
    }).join('');

    // Click handlers for template selection.
    grid.querySelectorAll('.style-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        grid.querySelectorAll('.style-tile').forEach(t => {
          t.classList.remove('selected');
          t.style.borderColor = 'var(--border-color)';
        });
        tile.classList.add('selected');
        tile.style.borderColor = 'var(--primary-color, #7c6cf0)';
        _selectedStyleTemplate = tile.getAttribute('data-style-id') || 'default';
      });
    });
  } catch (err) {
    grid.innerHTML = '<div style="color: var(--muted-color); font-size: 0.85rem; padding: 1rem 0;">加载失败</div>';
  }
}

async function loadProjects() {
  const projects = await API.get('/api/projects');
  const list = document.getElementById('project-list');
  list.innerHTML = '';

  if (projects.length === 0) {
    list.innerHTML = `
      <div class="card soft-outline" style="text-align: center; padding: 4rem 2rem; grid-column: 1/-1;">
        <p style="font-size: 1.2rem; margin-bottom: 1rem;">还没有项目，快去新建一个吧！</p>
        <button type="button" data-create-first-project>立即新建</button>
      </div>`;
    list.querySelector('[data-create-first-project]')?.addEventListener('click', () => {
      document.getElementById('btn-create-project')?.click();
    });
    return;
  }

  projects.forEach(project => {
    const status = project.step_status || {};
    const context = projectFlowContext(project);
    const percent = calculateVisibleProgress(status, context);
    const hasPendingReconfirm = VISIBLE_FLOW.some(
      item => getVisibleStepState(item.step, status, context) === 'pending_reconfirmation'
    );
    const currentVisibleStep = resolveProjectVisibleStep(project);

    // Automation badge from cached batch status.
    const autoInfo = _automationStatusMap[project.id];
    const badge = autoInfo ? _badgeFromStatus(autoInfo.status) : null;
    const showPauseBtn = autoInfo && autoInfo.status === 'running';
    const showResumeBtn = autoInfo && (autoInfo.status === 'paused' || autoInfo.status === 'waiting_for_user');

    const card = document.createElement('div');
    card.className = 'project-card soft-elevation';
    card.innerHTML = `
      <div>
        <div class="project-card-header">
          <h3 class="highlight-title">${escHtml(project.name)}</h3>
          ${badge ? `<span class="automation-badge ${badge.cls}" data-automation-badge data-project-id="${escHtml(project.id)}" title="${escHtml(autoInfo.current_stage || '')}">${badge.label}</span>` : `<span class="automation-badge" data-automation-badge data-project-id="${escHtml(project.id)}" style="display:none;"></span>`}
        </div>
        <p style="color: #666; font-size: 0.95rem; min-height: 40px; margin-bottom: 0.5rem;">${escHtml(project.description || '无项目描述')}</p>
        <div style="font-size: 0.9rem; margin-top: 0.5rem;">
          <div>当前阶段: <strong>第 ${visibleStepNumber(currentVisibleStep)} 步 · ${visibleStepLabel(currentVisibleStep)}</strong></div>
          ${hasPendingReconfirm ? '<div style="color: #c9a002; font-weight: bold;">有步骤需重做</div>' : ''}
        </div>
      </div>
      <div>
        <div class="project-progress-bar">
          <div class="project-progress-fill" style="width: ${percent}%"></div>
        </div>
        <div style="text-align: right; font-size: 0.8rem; margin-top: 2px; color: #555;">完成度: ${percent}%</div>
        <div style="display: flex; gap: 0.8rem; margin-top: 1rem;">
          <button class="success" type="button" data-open-project style="flex: 1; justify-content: center; font-size: 0.95rem; padding: 0.4rem;">继续设计</button>
          ${showPauseBtn ? '<button class="secondary" type="button" data-pause-automation style="font-size: 0.9rem; padding: 0.4rem 0.8rem;">暂停</button>' : ''}
          ${showResumeBtn ? '<button class="secondary" type="button" data-resume-automation style="font-size: 0.9rem; padding: 0.4rem 0.8rem;">继续自动化</button>' : ''}
          <button class="danger" type="button" data-delete-project aria-label="删除项目" style="font-size: 0.95rem; padding: 0.4rem 0.6rem;">
            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>`;
    card.querySelector('[data-open-project]')?.addEventListener('click', () => enterWorkspace(project.id));
    card.querySelector('[data-delete-project]')?.addEventListener('click', () => deleteProject(project.id));
    card.querySelector('[data-pause-automation]')?.addEventListener('click', () => pauseAutomationFromCard(project.id));
    card.querySelector('[data-resume-automation]')?.addEventListener('click', () => resumeAutomationFromCard(project.id));
    list.appendChild(card);
  });

  // Fetch and render automation badges after cards are in the DOM.
  pollAutomationStatus();
}

async function createProject() {
  const name = document.getElementById('input-project-name').value.trim();
  const description = document.getElementById('input-project-desc').value.trim();
  const aiMode = (document.getElementById('input-project-ai-mode')?.value || 'auto').trim();
  const canvasProfile = (document.getElementById('input-project-canvas-profile')?.value || 'landscape_16_9').trim();

  if (!name) {
    showToast('请输入项目名称');
    return;
  }

  // Collect manual pause steps from checkboxes.
  const pauseSteps = Array.from(document.querySelectorAll('.create-pause-step:checked'))
    .map(cb => cb.value)
    .filter(Boolean);

  const result = await API.post('/api/projects', {
    name,
    description,
    ai_mode: aiMode,
    canvas_profile: canvasProfile,
    manual_pause_steps: pauseSteps,
    image_style_template: _selectedStyleTemplate || 'default',
  });
  if (!result.success) return;
  document.getElementById('modal-create').style.display = 'none';
  showToast('项目新建成功');

  // Apply the selected image-style template if it's not the default.
  const templateId = _selectedStyleTemplate || 'default';
  if (templateId && templateId !== 'default') {
    try {
      await API.post(`/api/projects/${result.project.id}/steps/3/image-style/templates/${encodeURIComponent(templateId)}/apply`);
    } catch (_) { /* non-fatal — user can apply manually in Step 3 */ }
  }

  enterWorkspace(result.project.id);
}

function deleteProject(id) {
  showCustomConfirm(
    '删除项目确认',
    '确定永久删除该项目及其全部素材和视频吗？此操作无法撤销。',
    async () => {
      const result = await API.delete(`/api/projects/${id}`);
      if (!result.success) return;
      showToast('项目已删除');
      loadProjects();
    }
  );
}
