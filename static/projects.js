// Project library rendering and lifecycle actions.

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

    const card = document.createElement('div');
    card.className = 'project-card soft-elevation';
    card.innerHTML = `
      <div>
        <div class="project-card-header">
          <h3 class="highlight-title">${escHtml(project.name)}</h3>
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
          <button class="danger" type="button" data-delete-project aria-label="删除项目" style="font-size: 0.95rem; padding: 0.4rem 0.6rem;">
            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>`;
    card.querySelector('[data-open-project]')?.addEventListener('click', () => enterWorkspace(project.id));
    card.querySelector('[data-delete-project]')?.addEventListener('click', () => deleteProject(project.id));
    list.appendChild(card);
  });
}

async function createProject() {
  const name = document.getElementById('input-project-name').value.trim();
  const description = document.getElementById('input-project-desc').value.trim();
  const aiMode = (document.getElementById('input-project-ai-mode')?.value || 'auto').trim();

  if (!name) {
    showToast('请输入项目名称');
    return;
  }

  const result = await API.post('/api/projects', { name, description, ai_mode: aiMode });
  if (!result.success) return;
  document.getElementById('modal-create').style.display = 'none';
  showToast('项目新建成功');
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

