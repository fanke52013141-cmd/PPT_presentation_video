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

function showToast(message, duration = 1800) {
  const container = document.getElementById('toast-container');
  const presentation = getToastPresentation(message);
  const toastKey = `${presentation.tone}:${presentation.text}`;
  const duplicate = Array.from(container.children).find(item => item.dataset.toastKey === toastKey);
  if (duplicate) return duplicate;
  while (container.children.length >= 4) {
    container.firstElementChild?.remove();
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${presentation.tone}`;
  toast.dataset.toastKey = toastKey;
  toast.setAttribute('role', presentation.tone === 'error' ? 'alert' : 'status');
  const content = document.createElement('div');
  content.className = 'toast-content';
  content.textContent = presentation.text;
  toast.appendChild(content);
  container.appendChild(toast);
  if (presentation.tone === 'error') {
    const close = document.createElement('button');
    close.className = 'toast-close';
    close.type = 'button';
    close.textContent = '关闭';
    close.addEventListener('click', event => {
      event.stopPropagation();
      toast.remove();
    });
    toast.appendChild(close);
    toast.title = '点击可复制完整异常信息';
    toast.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(String(message ?? ''));
        close.textContent = '已复制';
      } catch (_) {
        close.textContent = '复制失败';
      }
      toast.remove();
    });
    return;
  }
  // 通知类消息只短暂出现；异常类消息则由上方的关闭按钮明确处理。
  const visibleDuration = Math.max(1000, Math.min(2000, Number(duration) || 1800));
  setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease-in reverse';
    setTimeout(() => toast.remove(), 300);
  }, visibleDuration);
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

  newYes.addEventListener('click', async () => {
    modal.style.display = 'none';
    newYes.disabled = true;
    newNo.disabled = true;
    try {
      if (onYes) await onYes();
    } catch (error) {
      showToast(`操作失败：${error.message}`, 6000);
    } finally {
      newYes.disabled = false;
      newNo.disabled = false;
    }
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

// 失败信息需由用户显式关闭；点击正文可复制完整报错，避免截断后无法排查。
let failureBadgeLastKey = '';
let failureBadgeDismissedKey = '';
let failureBadgeTimer = null;

function showFailureBadge(key, message, detail) {
  const badgeKey = String(key || message || '').trim();
  const text = String(message || '').trim();
  if (!text || badgeKey === failureBadgeDismissedKey) return;
  failureBadgeLastKey = badgeKey;
  let badge = document.getElementById('failure-badge');
  if (!badge) {
    badge = document.createElement('div');
    badge.id = 'failure-badge';
    badge.className = 'failure-badge';
    badge.setAttribute('role', 'alert');
    document.body.appendChild(badge);
  }
  const dot = document.createElement('span');
  dot.className = 'failure-badge-dot';
  const body = document.createElement('div');
  body.className = 'failure-badge-body';
  const title = document.createElement('strong');
  title.textContent = text;
  body.appendChild(title);
  const detailText = String(detail || '').trim();
  if (detailText) {
    const line = document.createElement('small');
    line.textContent = detailText;
    body.appendChild(line);
  }
  badge.replaceChildren(dot, body);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'failure-badge-close';
  close.textContent = '关闭';
  close.addEventListener('click', event => {
    event.stopPropagation();
    failureBadgeDismissedKey = badgeKey;
    badge.remove();
  });
  badge.append(close);
  badge.style.display = 'flex';
  if (failureBadgeTimer) window.clearTimeout(failureBadgeTimer);
  badge.title = '点击可复制完整异常信息';
  badge.onclick = async () => {
    try { await navigator.clipboard.writeText(`${text}${detailText ? `\n${detailText}` : ''}`); } catch (_) {}
    failureBadgeDismissedKey = badgeKey;
    badge.remove();
  };
}
