// Step 1 article import, topic generation, editing, and prompt settings.

function appendStep1InlineMarkdown(target, text) {
  const parts = String(text ?? '').split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  parts.forEach(part => {
    if (!part) return;
    if (part.startsWith('**') && part.endsWith('**')) {
      const strong = document.createElement('strong');
      strong.textContent = part.slice(2, -2);
      target.appendChild(strong);
    } else if (part.startsWith('`') && part.endsWith('`')) {
      const code = document.createElement('code');
      code.textContent = part.slice(1, -1);
      target.appendChild(code);
    } else {
      target.appendChild(document.createTextNode(part));
    }
  });
}

function renderStep1MarkdownEditor(markdown) {
  const editor = document.getElementById('step1-markdown-editor');
  if (!editor) return;
  editor.replaceChildren();
  const lines = String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n');
  let previousWasBlank = false;
  lines.forEach(line => {
    if (!line.trim()) {
      if (previousWasBlank || (editor.childNodes.length === 0 && lines.length === 1)) return;
      const spacer = document.createElement('div');
      spacer.className = 'step1-md-spacer';
      spacer.dataset.markdownBlock = 'spacer';
      spacer.appendChild(document.createElement('br'));
      editor.appendChild(spacer);
      previousWasBlank = true;
      return;
    }
    previousWasBlank = false;

    const block = document.createElement('div');
    let prefix = '';
    let body = line;
    let type = 'paragraph';
    const heading = line.match(/^(#{1,2})\s+(.*)$/);
    const list = line.match(/^\s*[-*+]\s+(.*)$/);
    if (heading) {
      type = heading[1].length === 1 ? 'h1' : 'h2';
      prefix = `${heading[1]} `;
      body = heading[2];
    } else if (list) {
      type = 'list';
      prefix = '- ';
      body = list[1];
    }
    block.className = `step1-md-block step1-md-${type}`;
    block.dataset.markdownBlock = type;
    if (prefix) {
      const marker = document.createElement('span');
      marker.className = 'step1-markdown-marker';
      marker.dataset.markdownPrefix = prefix;
      marker.setAttribute('contenteditable', 'false');
      marker.setAttribute('aria-hidden', 'true');
      if (type !== 'list') marker.textContent = prefix.trim();
      block.appendChild(marker);
    }
    const content = document.createElement('span');
    content.className = 'step1-md-content';
    appendStep1InlineMarkdown(content, body);
    block.appendChild(content);
    editor.appendChild(block);
  });
  if (!String(markdown ?? '').trim()) editor.replaceChildren();
  updateStep1TopicArticleMeta(markdown);
}

function serializeStep1InlineMarkdown(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
  if (node.nodeType !== Node.ELEMENT_NODE) return '';
  if (node.classList?.contains('step1-markdown-marker')) return '';
  if (node.tagName === 'BR') return '\n';
  const children = Array.from(node.childNodes).map(serializeStep1InlineMarkdown).join('');
  if (node.tagName === 'STRONG' || node.tagName === 'B') return `**${children}**`;
  if (node.tagName === 'CODE') return `\`${children}\``;
  if (node.tagName === 'DIV' || node.tagName === 'P' || node.tagName === 'LI') return `${children}\n`;
  return children;
}

function syncStep1MarkdownToSource() {
  const editor = document.getElementById('step1-markdown-editor');
  const source = document.getElementById('step1-article-input');
  if (!source) return '';
  if (!editor) return source.value || '';
  const markdown = Array.from(editor.childNodes).map(node => {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    if (node.classList.contains('step1-md-spacer')) return '';
    const marker = node.querySelector('.step1-markdown-marker');
    const clone = node.cloneNode(true);
    clone.querySelectorAll('.step1-markdown-marker').forEach(element => element.remove());
    const body = serializeStep1InlineMarkdown(clone).replace(/\n+$/g, '');
    return `${marker?.dataset.markdownPrefix || ''}${body}`;
  }).join('\n').replace(/[\t ]+\n/g, '\n');
  source.value = markdown;
  updateStep1TopicArticleMeta(markdown);
  return markdown;
}

function updateStep1TopicArticleMeta(markdown = document.getElementById('step1-article-input')?.value || '') {
  const count = document.getElementById('step1-article-count');
  const copyButton = document.getElementById('step1-copy-article');
  const content = String(markdown).trim();
  if (count) count.textContent = content ? `已生成 • ${content.length} 字符` : '待生成';
  if (copyButton) copyButton.disabled = !content;
}

async function copyStep1Article() {
  const content = syncStep1MarkdownToSource().trim();
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
    showToast('文章已复制');
  } catch (error) {
    showToast('复制失败，请检查浏览器剪贴板权限');
  }
}

function pasteStep1PlainText(event) {
  const text = event.clipboardData?.getData('text/plain');
  if (text == null) return;
  event.preventDefault();
  if (document.queryCommandSupported?.('insertText')) {
    document.execCommand('insertText', false, text);
  } else {
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();
    range.insertNode(document.createTextNode(text));
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  syncStep1MarkdownToSource();
}

async function loadStep1Data() {
  renderPageTaskState(document.getElementById('step1-editor-shell'), 'article', null, '');
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const result = await API.get(`/api/projects/${projectId}/steps/1/result`);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
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
  renderStep1MarkdownEditor(articleInput.value);
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
  const modeSwitch = document.querySelector('#step-panel-1 .step1-mode-switch');
  if (modeSwitch) modeSwitch.dataset.activeMode = normalized;
  const importView = document.getElementById('step1-import-view');
  const topicView = document.getElementById('step1-topic-view');
  document.querySelector('#step-panel-1 .step1-content-card')?.classList.toggle('is-topic', normalized === 'topic');
  const editorShell = document.getElementById('step1-editor-shell');
  const topicEditorSlot = document.getElementById('step1-topic-editor-slot');
  const editorTarget = normalized === 'topic' ? topicEditorSlot : importView;
  if (editorShell && editorTarget && editorShell.parentElement !== editorTarget) {
    editorTarget.appendChild(editorShell);
  }
  if (importView) importView.style.display = normalized === 'article' ? 'flex' : 'none';
  if (topicView) topicView.style.display = normalized === 'topic' ? 'flex' : 'none';
  updateStep1TopicArticleMeta();
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
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const topic = document.getElementById('step1-topic-input')?.value.trim() || '';
  if (!topic) {
    showToast('请先输入一个话题');
    return;
  }
  const button = document.getElementById('step1-btn-generate-article');
  const originalHtml = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '生成中…';
  renderPageTaskState(document.getElementById('step1-editor-shell'), 'article', 'running', '正在根据话题生成文章', 'text');
  try {
    const result = await API.post(
      `/api/projects/${projectId}/steps/1/generate-article`,
      { topic },
    );
    // 文章生成可能等待数分钟：迟到响应不得把 A 项目生成的文章写进已切换
    // 到的 B 项目编辑器。
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    const articleInput = document.getElementById('step1-article-input');
    articleInput.value = result.content || '';
    renderStep1MarkdownEditor(articleInput.value);
    autoResizeTextarea(articleInput);
    document.getElementById('step1-status-hint').innerText = '文章已生成，可编辑后保存';
    renderPageTaskState(document.getElementById('step1-editor-shell'), 'article', 'done', '文章已生成');
    showToast('AI 文章已生成');
  } catch (error) {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) renderPageTaskState(document.getElementById('step1-editor-shell'), 'article', 'error', `文章生成失败：${error.message}`);
    throw error;
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

async function submitStep1() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const content = syncStep1MarkdownToSource().trim();
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
      `/api/projects/${projectId}/steps/1/import`,
      formData,
    );
    if (!isCurrentWorkspaceProject(projectId, sessionVersion) || !result.success) return;
    document.getElementById('step1-res-title').value = result.brief.title;
    document.getElementById('step1-res-summary').value = result.brief.summary || '';
    document.getElementById('step1-result-box').style.display = 'none';
    document.getElementById('step1-status-hint').innerText = '文章已保存';
    state.currentProject.current_step = Math.max(state.currentProject.current_step, 2);
    state.currentProject.step_status['1'] = 'completed';
    updateStepperUI(1, state.currentProject.step_status);
    showToast('文章已保存，进入分镜规划');
    await navigateToStep(2);
  } finally {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      submitButton.disabled = false;
      submitButton.innerHTML = originalHtml;
    }
  }
}

async function saveStep1Edit() {
  const content = syncStep1MarkdownToSource().trim();
  if (!content) {
    showToast('文章内容不能为空');
    return;
  }
  // 「保存修改」按钮已按用户要求移除（进入分镜规划即保存），此函数保留给
  // 后续自动保存复用；按钮引用全部可空化。
  const button = document.getElementById('step1-btn-save-edit');
  const originalHtml = button?.innerHTML ?? '';
  if (button) {
    button.disabled = true;
    button.innerHTML = '保存中...';
  }
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
    if (button) {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }
}

