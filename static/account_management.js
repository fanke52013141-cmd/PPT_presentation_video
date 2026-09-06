// Current creative-account selector. The selected account is stored server-side
// in an HttpOnly cookie; the browser never carries model credentials.

let _accounts = [];

function closeAccountPicker() {
  const menu = document.getElementById('account-picker-menu');
  const trigger = document.getElementById('account-picker-trigger');
  if (menu) menu.hidden = true;
  trigger?.setAttribute('aria-expanded', 'false');
}

function renderAccountPicker() {
  const select = document.getElementById('current-account-select');
  const menu = document.getElementById('account-picker-menu');
  const trigger = document.getElementById('account-picker-trigger');
  const name = document.getElementById('account-picker-name');
  const avatar = document.getElementById('account-picker-avatar');
  if (!select || !menu || !trigger) return;

  const currentId = select.value || _accounts[0]?.id;
  const current = _accounts.find(account => account.id === currentId) || _accounts[0];
  const currentName = current?.name || '默认创作账号';
  if (name) name.textContent = currentName;
  if (avatar) avatar.textContent = currentName.slice(0, 1) || '默';

  menu.replaceChildren();
  _accounts.forEach(account => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'account-picker-option';
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', String(account.id === currentId));
    option.innerHTML = '<span class="account-picker-option-avatar"></span><span class="account-picker-option-copy"><strong></strong></span><span class="account-picker-status-dot" aria-label="当前使用中" hidden></span>';
    option.querySelector('.account-picker-option-avatar').textContent = (account.name || account.id || '账').slice(0, 1);
    option.querySelector('strong').textContent = account.name || account.id;
    const activeDot = option.querySelector('.account-picker-status-dot');
    if (activeDot) activeDot.hidden = account.id !== currentId;
    option.addEventListener('click', async () => {
      closeAccountPicker();
      if (account.id !== select.value) await selectAccount(account.id);
    });
    menu.appendChild(option);
  });
}

function toggleAccountPicker() {
  const menu = document.getElementById('account-picker-menu');
  const trigger = document.getElementById('account-picker-trigger');
  if (!menu || !trigger) return;
  const willOpen = menu.hidden;
  if (willOpen) renderAccountPicker();
  menu.hidden = !willOpen;
  trigger.setAttribute('aria-expanded', String(willOpen));
}

function ensureAccountDialog() {
  let dialog = document.getElementById('account-create-dialog');
  if (dialog) return dialog;
  dialog = document.createElement('div');
  dialog.id = 'account-create-dialog';
  dialog.className = 'modal-overlay account-create-dialog';
  dialog.style.display = 'none';
  dialog.innerHTML = `
    <div class="modal-content account-create-panel" role="dialog" aria-modal="true" aria-labelledby="account-create-title">
      <div class="modal-header-row">
        <div>
          <div class="eyebrow-label">账号中心</div>
          <h3 id="account-create-title" class="highlight-title">创建创作账号</h3>
        </div>
        <button type="button" class="icon-button" data-account-close aria-label="关闭">×</button>
      </div>
      <p class="account-create-help">每个账号拥有独立的课程、项目、模型关联和创作配置。创建后会自动切换到新账号。</p>
      <label class="form-field">
        <span>账号名称</span>
        <input id="account-create-name" type="text" maxlength="200" autocomplete="off" placeholder="例如：科普账号 / 课程制作组">
        <small>建议使用容易识别的内容品牌或团队名称。</small>
      </label>
      <div class="modal-actions">
        <button type="button" class="secondary" data-account-cancel>取消</button>
        <button type="button" class="success" data-account-submit>创建并切换</button>
      </div>
    </div>`;
  document.body.appendChild(dialog);
  const close = () => {
    dialog.style.display = 'none';
    document.getElementById('account-create-name')?.focus();
  };
  dialog.querySelector('[data-account-close]')?.addEventListener('click', close);
  dialog.querySelector('[data-account-cancel]')?.addEventListener('click', close);
  dialog.addEventListener('click', event => {
    if (event.target === dialog) close();
  });
  dialog.querySelector('[data-account-submit]')?.addEventListener('click', async () => {
    const input = document.getElementById('account-create-name');
    const name = String(input?.value || '').trim();
    if (!name) {
      input?.focus();
      if (typeof window.showToast === 'function') window.showToast('请输入账号名称');
      return;
    }
    const submit = dialog.querySelector('[data-account-submit]');
    submit.disabled = true;
    try {
      const created = await API.post('/api/accounts', { name });
      close();
      await loadAccounts();
      const select = document.getElementById('current-account-select');
      const createdId = created?.account?.id || created?.id;
      if (select && _accounts.some(item => item.id === createdId)) {
        select.value = createdId;
        await selectAccount(createdId);
      }
      if (typeof window.showToast === 'function') window.showToast('账号已创建并切换');
    } catch (_) {
      // API client renders the server error; keep the dialog open so the user
      // can correct the name without losing what they entered.
    } finally {
      submit.disabled = false;
    }
  });
  document.getElementById('account-create-name')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') dialog.querySelector('[data-account-submit]')?.click();
    if (event.key === 'Escape') close();
  });
  return dialog;
}

function ensureAgentTokenDialog() {
  let dialog = document.getElementById('agent-token-dialog');
  if (dialog) return dialog;
  dialog = document.createElement('div');
  dialog.id = 'agent-token-dialog';
  dialog.className = 'modal-overlay account-create-dialog';
  dialog.style.display = 'none';
  dialog.innerHTML = `
    <div class="modal-content account-create-panel" role="dialog" aria-modal="true" aria-labelledby="agent-token-title">
      <div class="modal-header-row">
        <div><div class="eyebrow-label">Agent 对接</div><h3 id="agent-token-title" class="highlight-title">生成 Agent Token</h3></div>
        <button type="button" class="icon-button" data-agent-close aria-label="关闭">×</button>
      </div>
      <p class="account-create-help">Token 只在生成后显示一次。请复制到 Agent 的安全凭据存储中，不要提交到代码仓库。</p>
      <label class="form-field"><span>Token 名称</span><input id="agent-token-name" type="text" maxlength="200" value="PPT Studio Agent"></label>
      <div id="agent-token-result" class="agent-token-result" hidden>
        <label class="form-field"><span>新 Token</span><textarea id="agent-token-value" rows="3" readonly spellcheck="false"></textarea></label>
        <button type="button" class="secondary" data-agent-copy>复制 Token</button>
      </div>
      <div class="modal-actions"><button type="button" class="secondary" data-agent-cancel>取消</button><button type="button" class="success" data-agent-submit>生成 Token</button></div>
    </div>`;
  document.body.appendChild(dialog);
  const close = () => { dialog.style.display = 'none'; };
  dialog.querySelector('[data-agent-close]')?.addEventListener('click', close);
  dialog.querySelector('[data-agent-cancel]')?.addEventListener('click', close);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.querySelector('[data-agent-copy]')?.addEventListener('click', async () => {
    const value = document.getElementById('agent-token-value')?.value || '';
    try {
      await navigator.clipboard.writeText(value);
      if (typeof window.showToast === 'function') window.showToast('Token 已复制');
    } catch (_) {
      document.getElementById('agent-token-value')?.select();
      if (typeof window.showToast === 'function') window.showToast('浏览器未授权自动复制，请手动复制');
    }
  });
  dialog.querySelector('[data-agent-submit]')?.addEventListener('click', async () => {
    const submit = dialog.querySelector('[data-agent-submit]');
    const name = document.getElementById('agent-token-name')?.value.trim() || 'PPT Studio Agent';
    submit.disabled = true;
    try {
      const current = await API.get('/api/accounts/current');
      const accountId = current?.account?.id;
      if (!accountId) throw new Error('未找到当前创作账号');
      const response = await API.post(`/api/accounts/${encodeURIComponent(accountId)}/agent-tokens`, { name });
      const token = response?.token?.token || response?.token;
      if (!token) throw new Error('服务未返回 Token');
      const result = document.getElementById('agent-token-result');
      const field = document.getElementById('agent-token-value');
      if (field) field.value = token;
      if (result) result.hidden = false;
      submit.textContent = '已生成';
      if (typeof window.showToast === 'function') window.showToast('Token 已生成，请立即复制并妥善保存');
    } catch (error) {
      if (typeof window.showToast === 'function') window.showToast(`Token 生成失败：${error.message || error}`);
    } finally {
      submit.disabled = false;
    }
  });
  return dialog;
}

function openAgentTokenDialog() {
  const dialog = ensureAgentTokenDialog();
  dialog.style.display = 'flex';
  document.getElementById('agent-token-result')?.setAttribute('hidden', '');
  const submit = dialog.querySelector('[data-agent-submit]');
  if (submit) { submit.disabled = false; submit.textContent = '生成 Token'; }
  document.getElementById('agent-token-name')?.focus();
}

async function loadAccounts() {
  const select = document.getElementById('current-account-select');
  if (!select) return;
  try {
    const [data, current] = await Promise.all([
      API.get('/api/accounts'),
      API.get('/api/accounts/current')
    ]);
    _accounts = Array.isArray(data?.accounts) ? data.accounts : [];
    const currentId = current?.account?.id || 'default';
    select.replaceChildren();
    _accounts.forEach(account => {
      const option = document.createElement('option');
      option.value = account.id;
      option.textContent = account.name || account.id;
      option.selected = account.id === currentId;
      select.appendChild(option);
    });
    renderAccountPicker();
  } catch (_) {
    select.replaceChildren();
    const option = document.createElement('option');
    option.textContent = '账号加载失败';
    select.appendChild(option);
    renderAccountPicker();
  }
}

async function selectAccount(accountId) {
  if (!accountId) return;
  try {
    await API.post(`/api/accounts/${encodeURIComponent(accountId)}/select`, {});
    // A workspace must be reloaded under the new owner; active jobs continue
    // with their persisted project account and configuration snapshot.
    if (typeof exitWorkspace === 'function' && state?.currentProject) exitWorkspace();
    await loadAccounts();
    await loadProjects();
    showToast('已切换创作账号');
  } catch (_) {
    await loadAccounts();
  }
}

async function createCreativeAccount() {
  const dialog = ensureAccountDialog();
  dialog.style.display = 'flex';
  const input = document.getElementById('account-create-name');
  if (input) {
    input.value = '';
    window.setTimeout(() => input.focus(), 0);
  }
}

function initAccountManagement() {
  document.getElementById('current-account-select')?.addEventListener('change', event => {
    selectAccount(event.target.value);
  });
  document.getElementById('account-picker-trigger')?.addEventListener('click', event => {
    event.stopPropagation();
    toggleAccountPicker();
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.account-switcher')) closeAccountPicker();
  });
  document.getElementById('btn-create-account')?.addEventListener('click', createCreativeAccount);
  document.getElementById('btn-open-agent')?.addEventListener('click', openAgentTokenDialog);
  document.getElementById('system-settings-open-agent')?.addEventListener('click', openAgentTokenDialog);
}

window.loadAccounts = loadAccounts;
window.initAccountManagement = initAccountManagement;
