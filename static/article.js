// Step 1 article import, topic generation, editing, and prompt settings.

async function loadStep1Data() {
  const result = await API.get(`/api/projects/${state.currentProject.id}/steps/1/result`);
  const articleInput = document.getElementById('step1-article-input');
  const statusHint = document.getElementById('step1-status-hint');
  const saveEditButton = document.getElementById('step1-btn-save-edit');

  if (result.success && result.brief) {
    articleInput.value = result.brief.content || '';
    document.getElementById('step1-res-title').value = result.brief.title || '';
    document.getElementById('step1-res-summary').value = result.brief.summary || '';
    if (statusHint) statusHint.innerText = '文章已保存，可以继续修改';
    if (saveEditButton) saveEditButton.style.display = 'inline-flex';
  } else {
    articleInput.value = '';
    document.getElementById('step1-res-title').value = '';
    document.getElementById('step1-res-summary').value = '';
    if (statusHint) statusHint.innerText = '';
    if (saveEditButton) saveEditButton.style.display = 'none';
  }

  document.getElementById('step1-result-box').style.display = 'none';
  setStep1Mode('article');
  requestAnimationFrame(() => autoResizeTextarea(articleInput));
}

function setStep1Mode(mode) {
  const normalized = mode === 'topic' ? 'topic' : 'article';
  state.articleInputMode = normalized;
  document.querySelectorAll('[data-step1-mode]').forEach(button => {
    const active = button.dataset.step1Mode === normalized;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const topicPanel = document.getElementById('step1-topic-panel');
  if (topicPanel) topicPanel.style.display = normalized === 'topic' ? 'block' : 'none';
}

function ensureArticleSystemContentModal() {
  let modal = document.getElementById('modal-article-system-content');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'modal-article-system-content';
  modal.className = 'modal-overlay';
  modal.style.display = 'none';
  modal.innerHTML = `
    <div class="modal-content config-editor-modal" style="max-width:820px;width:min(820px,94vw)">
      <div class="config-editor-scroll">
        <div class="prompt-title-row">
          <h3 class="highlight-title">话题生成文章 · System Content</h3>
          <button class="prompt-help-button" type="button" data-prompt-help="article" aria-label="查看话题生成文章的输入输出示例">?</button>
        </div>
        <p class="config-editor-note">这里的 System Content 可直接修改；问号中展示系统实际追加的 User Content 和输出格式示例。</p>
        <textarea id="article-generation-system-content" rows="18" spellcheck="false"></textarea>
      </div>
      <div class="config-editor-actions">
        <button id="btn-article-system-cancel" class="secondary" type="button">取消</button>
        <button id="btn-article-system-save" class="success" type="button">保存</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', event => {
    if (event.target === modal) modal.style.display = 'none';
  });
  modal.querySelector('#btn-article-system-cancel').addEventListener('click', () => {
    modal.style.display = 'none';
  });
  modal.querySelector('#btn-article-system-save').addEventListener('click', async () => {
    const button = modal.querySelector('#btn-article-system-save');
    const systemContent = modal.querySelector('#article-generation-system-content').value.trim();
    if (!systemContent) {
      showToast('System Content 不能为空');
      return;
    }
    button.disabled = true;
    try {
      await API.put('/api/settings/article-generation', { system_content: systemContent });
      modal.style.display = 'none';
      showToast('文章生成 System Content 已保存');
    } finally {
      button.disabled = false;
    }
  });
  return modal;
}

async function openArticleSystemContentModal() {
  const modal = ensureArticleSystemContentModal();
  modal.style.display = 'flex';
  const textarea = modal.querySelector('#article-generation-system-content');
  textarea.value = '加载中...';
  const result = await API.get('/api/settings/article-generation');
  textarea.value = result.system_content || '';
}

async function generateStep1Article() {
  const topic = document.getElementById('step1-topic-input')?.value.trim() || '';
  if (!topic) {
    showToast('请先输入一个话题');
    return;
  }
  const button = document.getElementById('step1-btn-generate-article');
  const originalText = button.textContent;
  button.disabled = true;
  button.innerHTML = '<span class="button-spinner"></span> 生成中...';
  try {
    const result = await API.post(
      `/api/projects/${state.currentProject.id}/steps/1/generate-article`,
      { topic },
    );
    const articleInput = document.getElementById('step1-article-input');
    articleInput.value = result.content || '';
    autoResizeTextarea(articleInput);
    document.getElementById('step1-status-hint').innerText = '文章已生成，可编辑后保存';
    showToast('AI 文章已生成');
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function submitStep1() {
  const content = document.getElementById('step1-article-input').value.trim();
  if (!content) {
    showToast('请输入 Markdown 文章内容');
    return;
  }
  const submitButton = document.getElementById('step1-btn-submit');
  const originalHtml = submitButton.innerHTML;
  submitButton.disabled = true;
  submitButton.innerHTML = '保存中...';
  const formData = new FormData();
  formData.append('content', content);

  try {
    const result = await API.post(
      `/api/projects/${state.currentProject.id}/steps/1/import`,
      formData,
    );
    if (!result.success) return;
    document.getElementById('step1-res-title').value = result.brief.title;
    document.getElementById('step1-res-summary').value = result.brief.summary || '';
    document.getElementById('step1-result-box').style.display = 'none';
    document.getElementById('step1-status-hint').innerText = '文章已保存';
    document.getElementById('step1-btn-save-edit').style.display = 'inline-flex';
    state.currentProject.current_step = Math.max(state.currentProject.current_step, 2);
    state.currentProject.step_status['1'] = 'completed';
    updateStepperUI(1, state.currentProject.step_status);
    showToast('文章已保存，进入分镜规划');
    await navigateToStep(2);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = originalHtml;
  }
}

async function saveStep1Edit() {
  const content = document.getElementById('step1-article-input').value.trim();
  if (!content) {
    showToast('文章内容不能为空');
    return;
  }
  const button = document.getElementById('step1-btn-save-edit');
  const originalHtml = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '保存中...';
  const payload = {
    title: state.currentProject?.name || document.getElementById('step1-res-title').value.trim(),
    summary: document.getElementById('step1-res-summary').value.trim(),
    content,
  };
  try {
    const result = await API.put(
      `/api/projects/${state.currentProject.id}/steps/1/result`,
      payload,
    );
    if (result.success) showToast('文章修改已保存');
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

