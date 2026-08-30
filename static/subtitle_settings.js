// Subtitle style form, live preview, persistence, and project-scoped font loading.
// Shared state, API helpers, escaping, and workflow refresh live in ui_foundation.js / workflow_state.js / api_client.js.

const DEFAULT_SUBTITLE_SETTINGS = {
  font_key: 'lxgw_marker_gothic',
  font_family: 'LXGW Marker Gothic',
  font_size: 40,
  font_weight: 400,
  bottom: 0,
  horizontal_margin: 110,
  color: '#000000',
  // 方案 B：TikTok 式整页分页 + 逐字高亮
  highlight_color: '#000000',
  paging_window_ms: 1300,
  token_highlight: true,
  max_lines: 1,
  line_height: 1.4,
};

function subtitleFontByKey(key) {
  return state.subtitleFonts.find(font => font.key === key) || {
    key: DEFAULT_SUBTITLE_SETTINGS.font_key,
    family: DEFAULT_SUBTITLE_SETTINGS.font_family,
  };
}

function readSubtitleSettingsForm() {
  const fontKey = document.getElementById('subtitle-font-key').value || DEFAULT_SUBTITLE_SETTINGS.font_key;
  const font = subtitleFontByKey(fontKey);
  const maxLines = Number(document.getElementById('subtitle-max-lines').value || 1);
  return {
    font_key: fontKey,
    font_family: font.family,
    font_size: Number(document.getElementById('subtitle-font-size').value || 40),
    font_weight: Number(document.getElementById('subtitle-font-weight').value || 400),
    bottom: Number(document.getElementById('subtitle-bottom').value || 0),
    horizontal_margin: Number(document.getElementById('subtitle-horizontal-margin').value || 110),
    color: document.getElementById('subtitle-color').value || '#000000',
    highlight_color: document.getElementById('subtitle-highlight-color').value || '#000000',
    paging_window_ms: Number(document.getElementById('subtitle-paging-window').value || 1300),
    token_highlight: document.getElementById('subtitle-token-highlight').checked,
    max_lines: Math.min(3, Math.max(1, maxLines)),
    line_height: 1.4,
  };
}

function populateSubtitleSettingsForm(settings) {
  const value = { ...DEFAULT_SUBTITLE_SETTINGS, ...(settings || {}) };
  document.getElementById('subtitle-font-key').value = value.font_key;
  document.getElementById('subtitle-font-size').value = String(value.font_size);
  document.getElementById('subtitle-font-weight').value = String(value.font_weight);
  document.getElementById('subtitle-bottom').value = String(value.bottom);
  document.getElementById('subtitle-horizontal-margin').value = String(value.horizontal_margin);
  document.getElementById('subtitle-color').value = String(value.color || '#000000');
  document.getElementById('subtitle-highlight-color').value = String(value.highlight_color || '#000000');
  document.getElementById('subtitle-paging-window').value = String(value.paging_window_ms || 1300);
  document.getElementById('subtitle-max-lines').value = String(value.max_lines || 1);
  document.getElementById('subtitle-token-highlight').checked = value.token_highlight !== false;
  updateSubtitlePreview();
}

function updateSubtitlePreview() {
  const stage = document.querySelector('.subtitle-preview-stage');
  const text = document.getElementById('subtitle-preview-text');
  if (!stage || !text) return;
  const settings = readSubtitleSettingsForm();
  const font = subtitleFontByKey(settings.font_key);
  const canvas = typeof getProjectCanvasGeometry === 'function'
    ? getProjectCanvasGeometry()
    : { width: 1920, height: 1080, aspectRatio: '16 / 9' };
  stage.style.aspectRatio = canvas.aspectRatio;
  const scale = Math.max(0.2, stage.clientWidth / canvas.width);
  const sample = document.getElementById('subtitle-sample-text').value.trim();
  const sampleText = sample || '这是一段视频字幕效果预览';
  text.style.fontFamily = `${font.family}, "Microsoft YaHei", sans-serif`;
  text.style.fontSize = `${settings.font_size * scale}px`;
  text.style.fontWeight = String(settings.font_weight);
  text.style.bottom = `${settings.bottom * scale}px`;
  text.style.left = `${settings.horizontal_margin * scale}px`;
  text.style.right = `${settings.horizontal_margin * scale}px`;
  text.style.color = settings.color;
  // 预览中加入逐字高亮示意：已播放部分高亮，未播放部分保持字幕颜色。
  const enableHighlight = settings.token_highlight !== false;
  if (enableHighlight) {
    const splitAt = Math.max(1, Math.floor(sampleText.length / 3));
    const highlighted = document.createElement('span');
    const pending = document.createElement('span');
    highlighted.textContent = sampleText.slice(0, splitAt);
    highlighted.style.color = settings.highlight_color;
    pending.textContent = sampleText.slice(splitAt);
    pending.style.color = settings.color;
    text.replaceChildren(highlighted, pending);
  } else {
    text.textContent = sampleText;
    text.style.color = settings.color;
  }
  text.style.lineHeight = String(settings.line_height || 1.4);
  text.style.whiteSpace = 'pre-wrap';
  text.style.wordBreak = 'keep-all';
  text.style.display = '-webkit-box';
  text.style.WebkitBoxOrient = 'vertical';
  text.style.WebkitLineClamp = String(settings.max_lines || 1);
  text.style.overflow = 'hidden';
  const marginWidth = settings.horizontal_margin * scale;
  const leftShade = document.getElementById('subtitle-margin-left-shade');
  const rightShade = document.getElementById('subtitle-margin-right-shade');
  const safeGuide = document.getElementById('subtitle-safe-width-guide');
  if (leftShade) leftShade.style.width = `${marginWidth}px`;
  if (rightShade) rightShade.style.width = `${marginWidth}px`;
  if (safeGuide) {
    safeGuide.style.left = `${marginWidth}px`;
    safeGuide.style.right = `${marginWidth}px`;
    const label = safeGuide.querySelector('span');
    if (label) label.textContent = `字幕可用宽度 ${Math.max(0, canvas.width - settings.horizontal_margin * 2)} px`;
  }
  document.getElementById('subtitle-font-size-value').textContent = String(settings.font_size);
  document.getElementById('subtitle-font-weight-value').textContent = String(settings.font_weight);
  document.getElementById('subtitle-bottom-value').textContent = String(settings.bottom);
  document.getElementById('subtitle-margin-value').textContent = String(settings.horizontal_margin);
  document.getElementById('subtitle-color-value').textContent = String(settings.color);
  document.getElementById('subtitle-highlight-color-value').textContent = String(settings.highlight_color);
  document.getElementById('subtitle-paging-window-value').textContent = String(settings.paging_window_ms);
  document.getElementById('subtitle-max-lines-value').textContent = String(settings.max_lines);
}

async function openSubtitleSettingsModal() {
  if (!state.currentProject?.id) return;
  const res = await API.get(`/api/projects/${state.currentProject.id}/subtitle-settings`);
  state.subtitleSettings = res.subtitle_style || { ...DEFAULT_SUBTITLE_SETTINGS };
  state.subtitleFonts = res.fonts || [];
  const fontSelect = document.getElementById('subtitle-font-key');
  fontSelect.innerHTML = state.subtitleFonts.map(font =>
    `<option value="${escHtml(font.key)}">${escHtml(font.label)}</option>`
  ).join('');
  const preview = document.getElementById('subtitle-preview-image');
  preview.src = res.preview_url || '';
  preview.style.display = res.preview_url ? 'block' : 'none';
  populateSubtitleSettingsForm(state.subtitleSettings);
  document.getElementById('modal-subtitle-settings').style.display = 'flex';
  requestAnimationFrame(updateSubtitlePreview);
}

function closeSubtitleSettingsModal() {
  document.getElementById('modal-subtitle-settings').style.display = 'none';
}

function resetSubtitleSettings() {
  populateSubtitleSettingsForm(DEFAULT_SUBTITLE_SETTINGS);
  showToast('字幕样式已恢复为默认值，点击保存后生效。');
}

async function saveSubtitleSettings() {
  const subtitle_style = readSubtitleSettingsForm();
  const res = await API.put(
    `/api/projects/${state.currentProject.id}/subtitle-settings`,
    { subtitle_style },
  );
  state.subtitleSettings = res.subtitle_style;
  populateSubtitleSettingsForm(state.subtitleSettings);
  closeSubtitleSettingsModal();
  showToast('字幕样式已保存，下一次视频渲染将使用当前字体、字号和位置。');
  refreshCurrentProjectStatus().catch(() => {});
}

