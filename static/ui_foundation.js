// Shared UI primitives and cross-step text/input helpers.

function getToastPresentation(message) {
  const rawMessage = String(message ?? '').trim();
  const text = rawMessage
    .replace(/^(?:[\p{Extended_Pictographic}\uFE0F\u200D]+\s*)+/u, '')
    .trim();

  let tone = 'info';
  if (/^(?:❌|⛔|🚫)/u.test(rawMessage) || /(失败|错误|异常)/.test(rawMessage)) {
    tone = 'error';
  } else if (/^(?:⚠️?|❗)/u.test(rawMessage) || /(请先|请填写|不能为空|缺少|无法|暂无)/.test(rawMessage)) {
    tone = 'warning';
  } else if (/^(?:✅|🎉|✨)/u.test(rawMessage) || /(成功|已保存|已确认|已完成|已删除|已应用|已启动)/.test(rawMessage)) {
    tone = 'success';
  }

  return { text: text || '操作已完成', tone };
}

function showToast(message, duration = 3000) {
  const container = document.getElementById('toast-container');
  while (container.children.length >= 4) {
    container.firstElementChild?.remove();
  }
  const presentation = getToastPresentation(message);
  const toast = document.createElement('div');
  toast.className = `toast toast-${presentation.tone}`;
  toast.setAttribute('role', presentation.tone === 'error' ? 'alert' : 'status');
  const content = document.createElement('div');
  content.className = 'toast-content';
  content.textContent = presentation.text;
  toast.appendChild(content);
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease-in reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function showCustomConfirm(title, message, onYes, onNo = null) {
  const modal = document.getElementById('modal-confirm');
  document.getElementById('confirm-title').innerText = title;
  document.getElementById('confirm-message').innerText = message;

  const btnYes = document.getElementById('btn-confirm-yes');
  const btnNo = document.getElementById('btn-confirm-no');

  // Clone controls so each confirmation owns exactly one callback pair.
  const newYes = btnYes.cloneNode(true);
  const newNo = btnNo.cloneNode(true);
  btnYes.parentNode.replaceChild(newYes, btnYes);
  btnNo.parentNode.replaceChild(newNo, btnNo);

  modal.style.display = 'flex';

  newYes.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onYes) onYes();
  });

  newNo.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onNo) onNo();
  });
}

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function narrationDedupeKey(text) {
  return String(text || '')
    .replace(/<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)/g, '')
    .toLocaleLowerCase()
    .replace(/[\s\p{P}\p{S}_]+/gu, '');
}

function uniqueNarrationLines(lines) {
  const seen = new Set();
  return (lines || []).filter(text => {
    const key = narrationDedupeKey(text);
    if (key && seen.has(key)) return false;
    if (key) seen.add(key);
    return true;
  });
}

function autoResizeTextarea(textarea) {
  if (!textarea) return;
  if (textarea.tagName === 'TEXTAREA') textarea.rows = 1;
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight + 2}px`;
}
