// 全局状态管理
let state = {
  currentProject: null,
  currentStep: 1,
  slides: [], // 第二步及后续的分镜/图片/Mask数据
  activeSlideIndex: 0, // 步骤2/3/5/6中当前激活的 slide 索引
  settings: {},
  canvasState: {
    boxes: [], // 当前 slide 的标注框列表 [{group_id: '', box: [x1,y1,x2,y2], text_label: '', role: ''}]
    selectedBoxIndex: -1,
    draggedBoxIndex: -1,
    draggedHandle: null, // 'nw', 'ne', 'se', 'sw', 'move'
    startX: 0,
    startY: 0
  }
};

// API 请求工具方法
const API = {
  async fetch(url, options = {}) {
    try {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '请求失败');
      }
      return data;
    } catch (error) {
      showToast(`❌ 错误: ${error.message}`);
      throw error;
    }
  },
  
  async get(url) {
    return this.fetch(url);
  },
  
  async post(url, body) {
    const isFormData = body instanceof FormData;
    return this.fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' }
    });
  },
  
  async put(url, body) {
    return this.fetch(url, {
      method: 'PUT',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' }
    });
  },
  
  async delete(url) {
    return this.fetch(url, { method: 'DELETE' });
  }
};

// Toast 提示
function showToast(message, duration = 3000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease-in reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// 全局手绘风格自定义确认弹窗
function showCustomConfirm(title, message, onYes, onNo = null) {
  const modal = document.getElementById('modal-confirm');
  document.getElementById('confirm-title').innerText = title;
  document.getElementById('confirm-message').innerText = message;
  
  const btnYes = document.getElementById('btn-confirm-yes');
  const btnNo = document.getElementById('btn-confirm-no');
  
  // 克隆节点清除旧事件
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

// 首次加载初始化
document.addEventListener('DOMContentLoaded', () => {
  initGlobalEvents();
  loadProjects();
  loadSettings();
});

// 初始化全局页面级事件监听
function initGlobalEvents() {
  // 顶栏按钮
  document.getElementById('btn-open-settings').addEventListener('click', () => openSettingsModal());
  document.getElementById('btn-settings-cancel').addEventListener('click', () => closeSettingsModal());
  document.getElementById('btn-settings-save').addEventListener('click', () => saveSettings());
  document.getElementById('btn-back-home').addEventListener('click', () => exitWorkspace());
  
  // 绑定设置测试连通性按钮
  document.getElementById('btn-test-llm').addEventListener('click', () => testLlmConnection());
  document.getElementById('btn-test-image').addEventListener('click', () => testImageConnection());
  document.getElementById('btn-test-tts').addEventListener('click', () => testTtsConnection());
  
  // 新建项目 Modal
  document.getElementById('btn-create-project').addEventListener('click', () => {
    document.getElementById('input-project-name').value = '';
    document.getElementById('input-project-desc').value = '';
    document.getElementById('modal-create').style.display = 'flex';
  });
  document.getElementById('btn-create-cancel').addEventListener('click', () => {
    document.getElementById('modal-create').style.display = 'none';
  });
  document.getElementById('btn-create-submit').addEventListener('click', () => createProject());

  // 设置面板 Tab 切换
  const tabs = document.querySelectorAll('#modal-settings .tab-item');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('#modal-settings .tab-pane').forEach(p => p.style.display = 'none');
      document.getElementById(tab.dataset.tab).style.display = 'block';
    });
  });

  // 步骤条点击导航
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    item.addEventListener('click', () => {
      const step = parseInt(item.dataset.step);
      const stepStatus = state.currentProject.step_status;
      const currentStep = state.currentProject.current_step;
      // 解锁逻辑：
      // 1. 目标步骤小于等于当前进行中的步骤 (step <= currentStep)
      // 2. 目标步骤已经被标记完成 (completed) 或待重新确认 (pending_reconfirmation)
      // 3. 目标步骤的前一步已经完成或待确认 (说明下一步已解锁，支持点击)
      const isUnlocked = step <= currentStep
        || stepStatus[step.toString()] === 'completed'
        || stepStatus[step.toString()] === 'pending_reconfirmation'
        || (step > 1 && (stepStatus[(step - 1).toString()] === 'completed' || stepStatus[(step - 1).toString()] === 'pending_reconfirmation'));
      if (isUnlocked) {
        navigateToStep(step);
      } else {
        showToast(`⚠️ 请先完成前序步骤再进行第 ${step} 步操作`);
      }
    });
  });

  // 流水线中所有的“下一步”按钮
  document.querySelectorAll('.btn-next-step').forEach(btn => {
    btn.addEventListener('click', () => {
      if (state.currentStep === 3) {
        navigateToStep(5);
      } else if (state.currentStep < 8) {
        navigateToStep(state.currentStep + 1);
      }
    });
  });

  // ================= 步骤 1 事件 =================
  document.getElementById('step1-btn-submit').addEventListener('click', () => submitStep1());
  document.getElementById('step1-btn-save-edit').addEventListener('click', () => saveStep1Edit());

  // ================= 步骤 2 事件 =================
  document.getElementById('step2-btn-generate').addEventListener('click', () => generateStep2Contract());
  document.getElementById('step2-btn-save').addEventListener('click', () => saveStep2Contract());

  // ================= 步骤 3 事件 =================
  document.getElementById('step3-btn-generate').addEventListener('click', () => generateStep3Image());
  document.getElementById('step3-file-upload').addEventListener('change', (e) => uploadStep3Image(e));
  document.getElementById('step3-batch-upload').addEventListener('change', (e) => handleStep3BatchUpload(e));
  document.getElementById('step3-btn-copy-prompts').addEventListener('click', () => copyStep2Prompts());
  document.getElementById('step3-btn-confirm').addEventListener('click', () => confirmStep3Images());

  // ================= 步骤 4 事件 =================
  document.getElementById('step4-btn-confirm').addEventListener('click', () => confirmStep4Images());

  // ================= 步骤 5 事件 =================
  document.getElementById('step5-btn-automask').addEventListener('click', () => runStep5AutoMask());
  document.getElementById('step5-btn-save').addEventListener('click', () => saveStep5Masks());

  // ================= 步骤 6 事件 =================
  document.getElementById('step6-btn-init').addEventListener('click', () => initStep6Narration());
  document.getElementById('step6-btn-save').addEventListener('click', () => saveStep6Narration());

  // ================= 步骤 7 事件 =================
  document.getElementById('step7-btn-synthesize').addEventListener('click', () => runStep7TTS());

  // ================= 步骤 8 事件 =================
  document.getElementById('step8-btn-render').addEventListener('click', () => runStep8Render());
  document.getElementById('step8-btn-finish').addEventListener('click', () => exitWorkspace());
}

// ==================== 项目管理与系统设置逻辑 ====================

async function loadProjects() {
  const data = await API.get('/api/projects');
  const listEl = document.getElementById('project-list');
  listEl.innerHTML = '';
  
  if (data.length === 0) {
    listEl.innerHTML = `
      <div class="card sketch-dashed" style="text-align: center; padding: 4rem 2rem; grid-column: 1/-1;">
        <p style="font-size: 1.2rem; margin-bottom: 1rem;">还没有项目，快去新建一个吧！</p>
        <button onclick="document.getElementById('btn-create-project').click()">立即新建</button>
      </div>`;
    return;
  }
  
  data.forEach(p => {
    // 计算已完成步骤百分比
    const status = p.step_status || {};
    let completedCount = 0;
    for (let i = 1; i <= 8; i++) {
      if (status[i.toString()] === 'completed') completedCount++;
    }
    const percent = Math.round((completedCount / 8) * 100);
    
    // 检查是否有后续步骤标记为待重新确认
    let hasPendingReconfirm = false;
    for (let key in status) {
      if (status[key] === 'pending_reconfirmation') {
        hasPendingReconfirm = true;
        break;
      }
    }
    
    const card = document.createElement('div');
    card.className = 'project-card sketch-shadow';
    card.innerHTML = `
      <div>
        <div class="project-card-header">
          <h3 class="highlight-title">${p.name}</h3>
        </div>
        <p style="color: #666; font-size: 0.95rem; min-height: 40px; margin-bottom: 0.5rem;">${p.description || '无项目描述'}</p>
        <div style="font-size: 0.9rem; margin-top: 0.5rem;">
          <div>当前步骤: <strong>第 ${p.current_step} 步</strong></div>
          ${hasPendingReconfirm ? '<div style="color: #c9a002; font-weight: bold;">⚠️ 有步骤待重新确认</div>' : ''}
        </div>
      </div>
      <div>
        <div class="project-progress-bar">
          <div class="project-progress-fill" style="width: ${percent}%"></div>
        </div>
        <div style="text-align: right; font-size: 0.8rem; margin-top: 2px; color: #555;">完成度: ${percent}%</div>
        <div style="display: flex; gap: 0.8rem; margin-top: 1rem;">
          <button class="success" onclick="enterWorkspace('${p.id}')" style="flex: 1; justify-content: center; font-size: 0.95rem; padding: 0.4rem;">继续设计</button>
          <button class="danger" onclick="deleteProject('${p.id}')" style="font-size: 0.95rem; padding: 0.4rem 0.6rem;">
            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>
    `;
    listEl.appendChild(card);
  });
}

async function createProject() {
  const name = document.getElementById('input-project-name').value.trim();
  const desc = document.getElementById('input-project-desc').value.trim();
  
  if (!name) {
    showToast('⚠️ 请输入项目名称');
    return;
  }
  
  const res = await API.post('/api/projects', { name, description: desc });
  if (res.success) {
    document.getElementById('modal-create').style.display = 'none';
    showToast('🎉 项目新建成功！');
    enterWorkspace(res.project.id);
  }
}

async function deleteProject(id) {
  showCustomConfirm(
    '🗑️ 删除项目确认',
    '您确定要永久删除该项目及其所有的素材、视频文件吗？此操作不可逆！',
    async () => {
      const res = await API.delete(`/api/projects/${id}`);
      if (res.success) {
        showToast('🗑️ 项目删除成功');
        loadProjects();
      }
    }
  );
}

async function loadSettings() {
  state.settings = await API.get('/api/settings');
  
  // 填充设置输入框
  document.getElementById('setting-llm-base-url').value = state.settings.llm_base_url || '';
  document.getElementById('setting-llm-api-key').value = state.settings.llm_api_key || '';
  document.getElementById('setting-llm-model').value = state.settings.llm_model || '';
  document.getElementById('setting-vision-model').value = state.settings.vision_model || '';
  document.getElementById('setting-llm-temp').value = state.settings.llm_temperature || '0.7';
  
  document.getElementById('setting-image-base-url').value = state.settings.image_base_url || '';
  document.getElementById('setting-image-api-key').value = state.settings.image_api_key || '';
  document.getElementById('setting-image-model').value = state.settings.image_model || 'gpt-image-1';
  document.getElementById('setting-image-size').value = state.settings.image_size || '1024x1024';
  
  document.getElementById('setting-tts-endpoint').value = state.settings.tts_endpoint || '';
  document.getElementById('setting-tts-api-key').value = state.settings.tts_api_key || '';
  document.getElementById('setting-tts-model').value = state.settings.tts_model || '';
  document.getElementById('setting-tts-voice-id').value = state.settings.tts_voice_id || '';
  document.getElementById('setting-tts-speed').value = state.settings.tts_speed || '1.0';
  document.getElementById('setting-tts-volume').value = state.settings.tts_volume || '1.0';
  document.getElementById('setting-tts-pitch').value = state.settings.tts_pitch || '0';
}

function openSettingsModal() {
  document.getElementById('modal-settings').style.display = 'flex';
}

function closeSettingsModal() {
  document.getElementById('modal-settings').style.display = 'none';
}

async function saveSettings() {
  const settings = {
    llm_base_url: document.getElementById('setting-llm-base-url').value.trim(),
    llm_api_key: document.getElementById('setting-llm-api-key').value.trim(),
    llm_model: document.getElementById('setting-llm-model').value.trim(),
    vision_model: document.getElementById('setting-vision-model').value.trim(),
    llm_temperature: document.getElementById('setting-llm-temp').value.trim(),
    
    image_base_url: document.getElementById('setting-image-base-url').value.trim(),
    image_api_key: document.getElementById('setting-image-api-key').value.trim(),
    image_model: document.getElementById('setting-image-model').value.trim(),
    image_size: document.getElementById('setting-image-size').value.trim(),
    
    tts_endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    tts_api_key: document.getElementById('setting-tts-api-key').value.trim(),
    tts_model: document.getElementById('setting-tts-model').value.trim(),
    tts_voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    tts_speed: document.getElementById('setting-tts-speed').value.trim(),
    tts_volume: document.getElementById('setting-tts-volume').value.trim(),
    tts_pitch: document.getElementById('setting-tts-pitch').value.trim()
  };
  
  const res = await API.put('/api/settings', { settings });
  if (res.success) {
    state.settings = settings;
    closeSettingsModal();
    showToast('💾 系统全局设置保存成功');
  }
}

async function testLlmConnection() {
  const btn = document.getElementById('btn-test-llm');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-llm-base-url').value.trim() || null,
    api_key: document.getElementById('setting-llm-api-key').value.trim(),
    model: document.getElementById('setting-llm-model').value.trim()
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写文本模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-llm', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testImageConnection() {
  const btn = document.getElementById('btn-test-image');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-image-base-url').value.trim() || null,
    api_key: document.getElementById('setting-image-api-key').value.trim(),
    model: document.getElementById('setting-image-model').value.trim()
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写生图接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写生图模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-image', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testTtsConnection() {
  const btn = document.getElementById('btn-test-tts');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    api_key: document.getElementById('setting-tts-api-key').value.trim(),
    model: document.getElementById('setting-tts-model').value.trim(),
    voice_id: document.getElementById('setting-tts-voice-id').value.trim()
  };
  
  if (!payload.endpoint) {
    showToast('⚠️ 请填写语音接口地址 (Endpoint)');
    return;
  }
  if (!payload.api_key) {
    showToast('⚠️ 请填写语音接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写语音模型');
    return;
  }
  if (!payload.voice_id) {
    showToast('⚠️ 请填写音色标识');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-tts', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

function copyLlmUrlToImage() {
  const llmUrl = document.getElementById('setting-llm-base-url').value.trim();
  if (!llmUrl) {
    showToast('请先填写文本模型的接口地址');
    return;
  }
  document.getElementById('setting-image-base-url').value = llmUrl;
  showToast('✅ 已将文本模型 Base URL 同步到图片生成配置');
}

// ==================== 工作区视图控制逻辑 ====================

async function enterWorkspace(projectId) {
  const project = await API.get(`/api/projects/${projectId}`);
  state.currentProject = project;
  
  // 顶栏切换
  document.getElementById('project-info-header').style.display = 'block';
  document.getElementById('current-project-name').innerText = project.name;
  document.getElementById('btn-back-home').style.display = 'block';
  
  // 页面切换
  document.getElementById('page-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'flex';
  
  // 加载步骤状态并导航至当前步骤
  updateStepperUI(project.current_step, project.step_status);
  navigateToStep(project.current_step);
}

function exitWorkspace() {
  document.getElementById('project-info-header').style.display = 'none';
  document.getElementById('btn-back-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'none';
  document.getElementById('page-home').style.display = 'block';
  
  state.currentProject = null;
  loadProjects();
}

function updateStepperUI(currentStep, stepStatus) {
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    const step = parseInt(item.dataset.step);
    item.className = 'step-item'; // 重置
    
    if (step === currentStep) {
      item.classList.add('active');
    }
    
    const status = stepStatus[step.toString()];
    if (status === 'completed') {
      item.classList.add('completed');
    } else if (status === 'pending_reconfirmation') {
      item.classList.add('pending_reconfirmation');
      // 可以在此处插入一个状态角标
      let badge = item.querySelector('.step-status-tag');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'step-status-tag';
        item.appendChild(badge);
      }
      badge.innerText = '待确认';
    } else {
      const badge = item.querySelector('.step-status-tag');
      if (badge) badge.remove();
    }
  });
}

// 步骤面板切换
async function navigateToStep(step) {
  state.currentStep = step;
  
  // 隐藏所有面板
  document.querySelectorAll('.step-panel').forEach(panel => panel.style.display = 'none');
  
  // 显示指定步骤面板
  const panel = document.getElementById(`step-panel-${step}`);
  if (panel) panel.style.display = 'block';
  
  // 刷新左侧步骤条高亮，若当前步骤有改动则进行同步
  if (state.currentProject && state.currentProject.current_step !== step) {
    // 更新数据库步骤与后处理状态
    const res = await API.get(`/api/projects/${state.currentProject.id}`);
    state.currentProject = res;
  }
  updateStepperUI(step, state.currentProject.step_status);
  
  // 针对特定步骤加载结果数据
  loadStepData(step);
}

function loadStepData(step) {
  switch (step) {
    case 1:
      loadStep1Data();
      break;
    case 2:
      loadStep2Data();
      break;
    case 3:
      loadStep3Data();
      break;
    case 4:
      loadStep4Data();
      break;
    case 5:
      loadStep5Data();
      break;
    case 6:
      loadStep6Data();
      break;
    case 7:
      loadStep7Data();
      break;
    case 8:
      loadStep8Data();
      break;
  }
}

// ==================== 步骤 1: 导入文章 ====================

async function loadStep1Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/1/result`);
  if (res.success && res.brief) {
    document.getElementById('step1-article-input').value = res.brief.content || '';
    document.getElementById('step1-res-title').value = res.brief.title || '';
    document.getElementById('step1-res-summary').value = res.brief.summary || '';
    document.getElementById('step1-result-box').style.display = 'block';
  } else {
    document.getElementById('step1-article-input').value = '';
    document.getElementById('step1-result-box').style.display = 'none';
    const hint = document.getElementById('step1-status-hint');
    if (hint) hint.innerText = '';
    const saveEditBtn = document.getElementById('step1-btn-save-edit');
    if (saveEditBtn) saveEditBtn.style.display = 'none';
  }
}

async function submitStep1() {
  const content = document.getElementById('step1-article-input').value.trim();
  if (!content) {
    showToast('⚠️ 请输入 Markdown 文章内容');
    return;
  }
  const submitBtn = document.getElementById('step1-btn-submit');
  const origHtml = submitBtn.innerHTML;
  submitBtn.disabled = true;
  submitBtn.innerHTML = '提炼中...';
  showToast('🚀 正在提炼标题，请稍候...');
  const formData = new FormData();
  formData.append('content', content);
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/1/import`, formData);
    if (res.success) {
      showToast('✨ 提炼成功，正在进入分镜规划...');
      document.getElementById('step1-res-title').value = res.brief.title;
      document.getElementById('step1-res-summary').value = res.brief.summary || '';
      document.getElementById('step1-result-box').style.display = 'none';
      const hint = document.getElementById('step1-status-hint');
      if (hint) hint.innerText = '✅ 标题已提炼，已自动进入分镜规划';
      document.getElementById('step1-btn-save-edit').style.display = 'inline-flex';
      state.currentProject.current_step = Math.max(state.currentProject.current_step, 2);
      state.currentProject.step_status['1'] = 'completed';
      updateStepperUI(1, state.currentProject.step_status);
      setTimeout(() => {
        navigateToStep(2);
      }, 500);
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = origHtml;
  }
}

async function saveStep1Edit() {
  const title = document.getElementById('step1-res-title').value.trim();
  const summary = document.getElementById('step1-res-summary').value.trim();
  const content = document.getElementById('step1-article-input').value.trim();
  const payload = { title, summary, content };
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/1/result`, payload);
  if (res.success) {
    showToast('💾 修改已保存');
  }
}

async function loadStep2Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
  if (res.success && res.contract) {
    state.slides = res.contract.slides || [];
    renderStep2Workspace();
  } else {
    state.slides = [];
    document.getElementById('step2-editor-area').style.display = 'none';
    document.getElementById('step2-btn-generate').style.display = 'inline-flex';
    document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> 智能规划分镜`;
    document.getElementById('step2-btn-save').style.display = 'none';
    document.getElementById('step2-btn-next').style.display = 'none';
  }
}

async function generateStep2Contract() {
  document.getElementById('step2-loading').style.display = 'block';
  document.getElementById('step2-btn-generate').disabled = true;
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/execute`);
    if (res.success) {
      showToast('🎉 分镜规划已生成！');
      state.slides = res.contract.slides || [];
      renderStep2Workspace();
    }
  } catch(e) {
    // 捕获报错
  } finally {
    document.getElementById('step2-loading').style.display = 'none';
    document.getElementById('step2-btn-generate').disabled = false;
  }
}

function renderStep2Workspace() {
  document.getElementById('step2-editor-area').style.display = 'block';
  document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> 重新规划分镜`;
  document.getElementById('step2-btn-copy-prompts').style.display = 'inline-flex';
  document.getElementById('step2-btn-save').style.display = 'inline-flex';
  document.getElementById('step2-btn-next').style.display = 'inline-flex';
  
  // 渲染精简版横向缩略图（只显示 Slide 编号+主标题）
  const thumbsContainer = document.getElementById('step2-thumbs');
  thumbsContainer.style.display = 'flex'; // 显式呈现
  thumbsContainer.innerHTML = '';
  
  state.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card ${idx === state.activeSlideIndex ? 'active' : ''}`;
    thumb.style.cssText = 'min-width: 90px; max-width: 110px; padding: 0.4rem 0.5rem; cursor: pointer;';
    thumb.innerHTML = `
      <div style="font-size: 0.7rem; font-weight: bold; color: #888; margin-bottom: 2px;">${slide.slide_id}</div>
      <div style="font-size: 0.8rem; font-weight: bold; color: #111; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${slide.main_title || '无标题'}</div>
    `;
    thumb.addEventListener('click', () => {
      saveCurrentSlideInputToState();
      state.activeSlideIndex = idx;
      renderStep2Workspace();
    });
    thumbsContainer.appendChild(thumb);
  });
  
  // 加载当前 Slide 详情（只展示 core_message + visual_groups）
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    const slideIdEl = document.getElementById('step2-current-slide-id');
    const slideTitleEl = document.getElementById('step2-current-slide-title');
    if (slideIdEl) slideIdEl.innerText = slide.slide_id;
    if (slideTitleEl) slideTitleEl.innerText = slide.main_title ? `「${slide.main_title}」` : '';
    // 同步隐藏字段
    document.getElementById('step2-main-title').value = slide.main_title || '';
    document.getElementById('step2-subtitle').value = slide.subtitle || '';
    document.getElementById('step2-core-message').value = slide.core_message || '';
    
    // 渲染 visual_groups 属性编辑
    const groupsList = document.getElementById('step2-groups-list');
    groupsList.innerHTML = '';
    
    slide.visual_groups.forEach((group, gIdx) => {
      // 过滤不需要展示的 body_group_02
      if (group.id === 'body_group_02') return;

      const groupEl = document.createElement('div');
      groupEl.className = 'sketch-dashed';
      groupEl.style.cssText = 'padding: 0.8rem; background: #fff; margin-bottom: 0.6rem; border-radius: 8px;';
      
      const roleMap = {
        'title': '标题',
        'subtitle': '副标题',
        'content_body': '正文',
        'diagram': '图解',
        'summary': '总结',
        'annotation': '批注',
        'decoration': '装饰'
      };
      const chineseRole = roleMap[group.role] || group.role || '元素';

      groupEl.innerHTML = `
        <div style="display: flex; align-items: center; margin-bottom: 0.6rem;">
          <span style="font-size: 0.8rem; font-weight: bold; color: var(--ink-color); background: var(--primary-color); border: 2px solid var(--ink-color); border-radius: 4px; padding: 2px 8px; box-shadow: 1px 1px 0px 0px var(--ink-color);">${chineseRole}</span>
        </div>
        <div style="margin-bottom: 0.5rem;">
          <label style="font-size: 0.8rem; font-weight: bold; display: block; margin-bottom: 0.2rem; color: #555;">画面显示中文：</label>
          <input type="text" value="${escHtml(group.visible_text)}" placeholder="请输入页面上显示的中文文字" style="font-size: 0.85rem; padding: 4px 8px;" oninput="updateGroupField(${gIdx}, 'visible_text', this.value)">
        </div>
        <div>
          <label style="font-size: 0.8rem; font-weight: bold; display: block; margin-bottom: 0.2rem; color: #555;">线稿视觉描述：</label>
          <input type="text" value="${escHtml(group.visual_anchor)}" placeholder="请输入线稿画面的视觉描述元素" style="font-size: 0.85rem; padding: 4px 8px; color: #444;" oninput="updateGroupField(${gIdx}, 'visual_anchor', this.value)">
        </div>
      `;
      groupsList.appendChild(groupEl);
    });
  }
}

// 拼接并一键复制所有 Slide 的生图提示词
function copyStep2Prompts() {
  saveCurrentSlideInputToState();
  
  if (!state.slides || state.slides.length === 0) {
    showToast('⚠️ 暂无分镜规划数据，无法复制提示词');
    return;
  }
  
  const topicName = state.currentProject.name;
  let textParts = [];
  
  state.slides.forEach((slide) => {
    const mainTitle = slide.main_title || '';
    const subtitle = slide.subtitle || '';
    const anchors = [];
    
    (slide.visual_groups || []).forEach(g => {
      // 过滤掉 title / subtitle 角色和不希望展示的 body_group_02，防止打乱提示词
      if (g.role !== 'title' && g.role !== 'subtitle' && g.id !== 'body_group_02') {
        if (g.visible_text && g.visual_anchor) {
          anchors.push(`${g.visible_text}(${g.visual_anchor})`);
        } else if (g.visible_text) {
          anchors.push(g.visible_text);
        } else if (g.visual_anchor) {
          anchors.push(g.visual_anchor);
        }
      }
    });
    
    const anchorsStr = anchors.join('，');
    
    // 结合项目风格与线稿风预设拼接 Prompt 
    const prompt = `A warm, minimalist, hand-drawn vector line art style presentation slide for topic '${topicName}'. ` +
      `Title: '${mainTitle}'. ` +
      (subtitle ? `Subtitle: '${subtitle}'. ` : '') +
      `The slide contains the following visual elements and concepts: ${anchorsStr}. ` +
      `Uniform pure beige background #FFFDF7, clean empty bottom subtitle area. ` +
      `Ink black lines (#111111), fine rough hand-drawn strokes. ` +
      `Subtle single accent yellow highlight (#F9D65C) on key concepts. ` +
      `Minimalist whiteboard drawing, korean line art webtoon style, cute hand sketch, no shadows, no gradients.`;
      
    textParts.push(`--- Slide ${slide.slide_id} ---`);
    textParts.push(prompt);
    textParts.push(''); // 空行
  });
  
  const allPromptsText = textParts.join('\n');
  
  navigator.clipboard.writeText(allPromptsText).then(() => {
    showToast('📋 已成功复制所有 Slide 的生图提示词到剪贴板！');
  }).catch(err => {
    console.error('复制失败:', err);
    showToast('⚠️ 复制失败，请手动选择复制');
  });
}

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function updateGroupField(gIdx, field, val) {
  const slide = state.slides[state.activeSlideIndex];
  if (slide && slide.visual_groups[gIdx]) {
    slide.visual_groups[gIdx][field] = val;
  }
}

function saveCurrentSlideInputToState() {
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    slide.main_title = document.getElementById('step2-main-title').value;
    slide.subtitle = document.getElementById('step2-subtitle').value;
    slide.core_message = document.getElementById('step2-core-message').value;
  }
}

async function saveStep2Contract() {
  saveCurrentSlideInputToState();
  const payload = {
    version: "visual_contract_v1",
    topic: state.currentProject.topic || {
      topic_id: "topic_" + state.currentProject.id,
      topic_name: state.currentProject.name
    },
    slides: state.slides
  };
  
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/result`, payload);
  if (res.success) {
    showToast('💾 分镜规划已成功保存！');
  }
}

// ==================== 步骤 3: 图片生成 ====================

let slidePrompts = [];
// 全局图片顺序（用于拖拽排序）
let step3ImageOrder = []; // [{slide_id, exists, url}]

async function loadStep3Data() {
  // 优先加载分镜数据，保证即使无图片也能渲染占位卡
  if (!state.slides || state.slides.length === 0) {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      state.slides = contractRes.contract.slides || [];
    }
  }

  // 获取每个 slide 拼接的 Prompt
  try {
    const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
    if (promptRes.success) slidePrompts = promptRes.prompts || [];
  } catch(e) {}
  
  // 获取生成的图片文件状态
  refreshStep3Images();
}

async function refreshStep3Images() {
  let images = [];
  try {
    const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
    if (res.success) images = res.images || [];
  } catch(e) {}

  // 如果后端返回空列表但分镜数据已有，自动生成占位展示
  if (images.length === 0 && state.slides && state.slides.length > 0) {
    images = state.slides.map(s => ({ slide_id: s.slide_id, exists: false, url: '' }));
  }
  step3ImageOrder = images;
  renderStep3Grid();
}

function renderStep3Grid() {
  const grid = document.getElementById('step3-images-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const hasAnyImage = step3ImageOrder.some(img => img.exists);
  const confirmBtn = document.getElementById('step3-btn-confirm');
  if (confirmBtn) confirmBtn.style.display = hasAnyImage ? 'inline-flex' : 'none';

  step3ImageOrder.forEach((img, idx) => {
    const card = document.createElement('div');
    card.className = 'card sketch-shadow slide-card-draggable';
    card.setAttribute('draggable', 'true');
    card.style.cssText = 'padding: 0.8rem; position: relative; cursor: grab; background: var(--bg-color); margin-bottom: 0;';

    // 拖拽事件注册
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', idx);
      card.style.opacity = '0.4';
      card.style.border = '2px dashed var(--ink-color)';
    });

    card.addEventListener('dragover', (e) => {
      e.preventDefault(); // 允许放置
    });

    card.addEventListener('drop', (e) => {
      e.preventDefault();
      const draggedIdx = parseInt(e.dataTransfer.getData('text/plain'));
      const targetIdx = idx;
      if (draggedIdx !== targetIdx && !isNaN(draggedIdx)) {
        const temp = step3ImageOrder[draggedIdx];
        step3ImageOrder.splice(draggedIdx, 1);
        step3ImageOrder.splice(targetIdx, 0, temp);
        renderStep3Grid();
        showToast('🔀 顺序已调整，请点击“确认所有图片”自动重新命名绑定');
      }
    });

    card.addEventListener('dragend', () => {
      card.style.opacity = '1';
      card.style.border = '2px solid var(--ink-color)';
    });

    const previewHtml = img.exists
      ? `<img src="${img.url}" style="width: 100%; height: 100%; object-fit: cover;" title="点击预览并编辑此张 Slide">`
      : `<div style="width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.3rem; color: #888; background: #fffdf5;">
           <svg class="icon" viewBox="0 0 24 24" style="width: 20px; height: 20px; color: #aaa;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"></path></svg>
           <span style="font-size: 0.75rem; font-weight: 500;">暂无图片，点击上传/生成</span>
         </div>`;

    card.innerHTML = `
      <!-- 头部： slide 编号与控制按钮 -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem;">
        <div style="display: flex; align-items: center; gap: 0.3rem;">
          <span style="font-weight: bold; font-size: 0.95rem; color: var(--ink-color);">${img.slide_id}</span>
          <span style="font-size: 0.72rem; font-weight: bold; color: ${img.exists ? 'var(--ink-color)' : '#888'}; background: ${img.exists ? 'var(--success-color)' : '#f3f4f6'}; border: 1.5px solid var(--ink-color); border-radius: 4px; padding: 1px 4px;">
            ${img.exists ? '已就绪' : '待生成'}
          </span>
        </div>
        <div style="display: flex; gap: 0.3rem; align-items: center;">
          <button class="success" style="font-size: 0.72rem; padding: 0.2rem 0.4rem; box-shadow: 1px 1px 0px 0px var(--ink-color); margin: 0;" onclick="event.stopPropagation(); openStep3AI('${img.slide_id}')">
            AI生成
          </button>
          <label class="btn secondary" style="font-size: 0.72rem; padding: 0.2rem 0.4rem; cursor: pointer; box-shadow: 1px 1px 0px 0px var(--ink-color); display: inline-flex; align-items: center; gap: 0.1rem; margin: 0;">
            上传
            <input type="file" accept="image/*" style="display: none;" onchange="uploadStep3ImageById('${img.slide_id}', this)">
          </label>
        </div>
      </div>

      <!-- 预览区 -->
      <div class="img-preview-container" style="width: 100%; aspect-ratio: 16/9; position: relative; border: 2px solid var(--ink-color); border-radius: 6px; overflow: hidden; background: #fffdf5; cursor: pointer;" onclick="openStep3AI('${img.slide_id}')">
        ${previewHtml}
      </div>
    `;
    grid.appendChild(card);
  });
}

function moveStep3Image(idx, direction) {
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= step3ImageOrder.length) return;
  const tmp = step3ImageOrder[idx];
  step3ImageOrder[idx] = step3ImageOrder[newIdx];
  step3ImageOrder[newIdx] = tmp;
  renderStep3Grid();
  showToast('🔀 顺序已调整，请点击“确认所有图片”自动重新命名绑定');
}

window.moveStep3Image = moveStep3Image;

function openStep3AI(slideId) {
  // 刷新当前激活的 slide并展开 AI 生成展板
  state.activeSlideIndex = step3ImageOrder.findIndex(img => img.slide_id === slideId);
  const editor = document.getElementById('step3-editor');
  editor.style.display = 'block';
  document.getElementById('step3-slide-id-label').innerText = slideId;
  const pInfo = slidePrompts.find(p => p.slide_id === slideId);
  document.getElementById('step3-prompt-input').value = pInfo ? pInfo.prompt : '';
  const imgInfo = step3ImageOrder.find(img => img.slide_id === slideId);
  const prevEl = document.getElementById('step3-preview-box');
  if (imgInfo && imgInfo.exists) {
    prevEl.innerHTML = `<img src="${imgInfo.url}" style="width:100%; height:100%; object-fit:contain;">`;
  } else {
    prevEl.innerHTML = '<span style="color: #888;">暂无图片</span>';
  }
  editor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

window.openStep3AI = openStep3AI;

async function uploadStep3ImageById(slideId, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  showToast('📤 正在上传并裁剪为标准格式...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
  if (res.success) {
    showToast('🎉 图片上传成功！');
    refreshStep3Images();
  }
  input.value = '';
}

window.uploadStep3ImageById = uploadStep3ImageById;

// 批量上传处理
async function handleStep3BatchUpload(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;
  
  // 按分镜顺序逐一匹配上传
  const slideIds = step3ImageOrder.map(img => img.slide_id);
  showToast(`📤 正在批量上传 ${files.length} 张图片...`);
  
  for (let i = 0; i < files.length; i++) {
    const slideId = slideIds[i];
    if (!slideId) break;
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('file', files[i]);
    try {
      await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    } catch(err) {
      showToast(`⚠️ 第 ${i+1} 张上传失败`);
    }
  }
  showToast('✅ 批量上传完成！');
  refreshStep3Images();
  e.target.value = '';
}


// AI 生成单张图片（来自 AI 展板的提交）
async function generateStep3Image() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  const prompt = document.getElementById('step3-prompt-input').value.trim();
  
  if (!prompt) {
    showToast('⚠️ 提示词不能为空');
    return;
  }
  
  document.getElementById('step3-loading').style.display = 'block';
  document.getElementById('step3-btn-generate').disabled = true;
  showToast(`🎨 正在调用 ${state.settings?.image_model || 'gpt-image-1'} 合成 1536x1024 中...`);
  
  try {
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('prompt', prompt);
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/generate`, formData);
    if (res.success) {
      showToast('🎉 图片生成并已缩放裁剪至 1920x1080！');
      refreshStep3Images();
    }
  } catch(e) {
  } finally {
    document.getElementById('step3-loading').style.display = 'none';
    document.getElementById('step3-btn-generate').disabled = false;
  }
}

// 单张上传（来自 AI 展板的上传按钮，绑定了 id=step3-file-upload 的 input change）
async function uploadStep3Image(e) {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  if (!slideId || slideId === '--') {
    showToast('⚠️ 请先点击某张 Slide 的 AI 生成面板再上传');
    return;
  }
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  showToast('📤 正在上传并裁剪为标准格式...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
  if (res.success) {
    showToast('🎉 图片上传成功！');
    refreshStep3Images();
    // 同步更新 AI 展板预览
    document.getElementById('step3-preview-box').innerHTML =
      `<img src="${res.url || ''}" style="width:100%; height:100%; object-fit:contain;">`;
  }
  e.target.value = '';
}

async function confirmStep3Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    const formData = new FormData();
    formData.append('target_step', '5');
    const navRes = await API.post(`/api/projects/${state.currentProject.id}/navigate`, formData);
    if (navRes.success) {
      showToast('🔒 所有图片已确认并锁定！进入标注阶段。');
      navigateToStep(5);
    }
  }
}

// ==================== 步骤 4: 图片审核确认 ====================

async function loadStep4Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
  const grid = document.getElementById('step4-grid');
  grid.innerHTML = '';
  
  if (res.success) {
    res.images.forEach(img => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.padding = '0.5rem';
      card.innerHTML = `
        <div style="height: 140px; border: 1px solid #111; border-radius: 5px; background-color: #eee; overflow: hidden; margin-bottom: 0.5rem;">
          ${img.exists ? `<img src="${img.url}" style="width:100%; height:100%; object-fit:cover;">` : '<span style="color:#aaa; display:flex; align-items:center; justify-content:center; height:100%;">无图片</span>'}
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-weight:bold;">${img.slide_id}</span>
          <button class="secondary" style="font-size:0.8rem; padding: 2px 6px;" onclick="goToSlideStep3('${img.slide_id}')">🔄 重构</button>
        </div>
      `;
      grid.appendChild(card);
    });
  }
}

window.goToSlideStep3 = function(slideId) {
  // 查找 slideIndex 并在第3步渲染激活它
  const idx = state.slides.findIndex(s => s.slide_id === slideId);
  if (idx !== -1) {
    state.activeSlideIndex = idx;
    navigateToStep(3);
  }
};

async function confirmStep4Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    showToast('🔒 图片已锁定！坐标文件自动生成。接下来进入标注阶段。');
    navigateToStep(5);
  }
}

// ==================== 步骤 5: Mask 可视化标注 ====================

let manifestData = null;

let step2Contract = null; // 用于缓存步骤 2 分镜规划数据

async function loadStep5Data() {
  try {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      step2Contract = contractRes.contract;
    }
  } catch (e) {}

  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/5/result`);
  if (res.success && res.manifest) {
    manifestData = res.manifest;
    // 智能初始化每一页 slide 的状态并向下兼容
    manifestData.slides.forEach(s => {
      if (!s.status) {
        // 如果存在标注块尚未审核完成，则设为 pending，否则设为 completed
        const needsAdjustment = (s.groups || []).some(g => 
          g.review_status === "needs_manual_adjustment_after_image_gen" || 
          g.review_status === "auto_fitted_needs_review"
        );
        s.status = needsAdjustment ? "pending" : "completed";
      }
    });
    renderStep5Workspace();
  }
}

function renderStep5Workspace() {
  const thumbsContainer = document.getElementById('step5-thumbs');
  thumbsContainer.className = 'step5-slides-grid'; // 改用平铺换行类名
  thumbsContainer.innerHTML = '';
  
  manifestData.slides.forEach((slide, idx) => {
    const btn = document.createElement('div');
    const isCurrent = idx === state.activeSlideIndex;
    const isCompleted = slide.status === 'completed';
    
    let statusClass = '';
    let statusText = '待标注';
    let statusColor = '#888';
    
    if (isCurrent) {
      statusClass = 'active';
      statusText = '标注中';
      statusColor = '#d29a00';
    } else if (isCompleted) {
      statusClass = 'completed';
      statusText = '已标注';
      statusColor = '#4caf50';
    }
    
    btn.className = `step5-slide-btn ${statusClass}`;
    btn.innerHTML = `
      <div style="font-size: 0.85rem; font-weight: bold; color: var(--ink-color);">${slide.slide_id}</div>
      <div style="font-size: 0.65rem; margin-top: 0.15rem; color: ${statusColor}; font-weight: 500;">
        ${statusText === '已标注' ? '✓ 已标注' : statusText === '标注中' ? '✍ 标注中' : '待标注'}
      </div>
    `;
    
    btn.addEventListener('click', () => {
      saveStep5CurrentState();
      state.activeSlideIndex = idx;
      renderStep5Workspace();
    });
    thumbsContainer.appendChild(btn);
  });
  
  // 加载当前 Slide 详情
  const slide = manifestData.slides[state.activeSlideIndex];
  if (slide) {
    // 设置 Canvas 背景图
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    document.getElementById('step5-bg-img').src = imgUrl;
    
    // 初始化 canvas 标注框数据并重绘
    state.canvasState.boxes = JSON.parse(JSON.stringify(slide.reveal_boxes || []));
    state.canvasState.selectedBoxIndex = -1;
    initCanvasEvents();
    redrawCanvas();
    
    // 渲染右侧属性列表
    renderStep5BoxesForm();
  }
}

function uuid() {
  return Math.random().toString(36).substring(2, 6);
}

// 渲染右侧的 box 编辑表单列表
function renderStep5BoxesForm() {
  const container = document.getElementById('step5-boxes-list');
  container.innerHTML = '';
  
  state.canvasState.boxes.forEach((box, idx) => {
    const isSelected = idx === state.canvasState.selectedBoxIndex;
    const item = document.createElement('div');
    item.className = 'sketch-dashed' + (isSelected ? ' highlight-glow' : '');
    item.style.padding = '0.5rem';
    item.style.backgroundColor = isSelected ? '#fffde0' : '#fff';
    item.style.borderWidth = isSelected ? '3px' : '2px';
    
    // 绑定坐标：box 包含 [x1, y1, x2, y2]
    const coords = box.box || [100, 100, 300, 300];
    const width = Math.round(coords[2] - coords[0]);
    const height = Math.round(coords[3] - coords[1]);
    
    // 关联查询画面中文、线稿描述和演讲稿旁白
    let visibleText = box.text_label || '';
    let spokenText = '';
    let visualAnchor = '';
    
    if (step2Contract && step2Contract.slides) {
      const currentSlideId = manifestData.slides[state.activeSlideIndex].slide_id;
      const step2Slide = step2Contract.slides.find(s => s.slide_id === currentSlideId);
      if (step2Slide) {
        // 从 visual_groups 提取 visible_text 和 visual_anchor
        const vGroup = (step2Slide.visual_groups || []).find(g => g.id === box.group_id);
        if (vGroup) {
          if (!visibleText) visibleText = vGroup.visible_text || '';
          visualAnchor = vGroup.visual_anchor || '';
        }
        // 从 narration_beats 提取 spoken_text (旁白文字)
        const beat = (step2Slide.narration_beats || []).find(b => b.group_id === box.group_id);
        if (beat) {
          spokenText = beat.spoken_text || '';
        }
      }
    }
    
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
        <span style="font-weight:bold; color:var(--ink-color); font-size:0.9rem;">标注块 ${idx+1} [${box.group_id}]</span>
        <button class="danger" style="font-size:0.75rem; padding:1px 5px;" onclick="deleteMaskBox(${idx})">删除</button>
      </div>
      <div style="margin-bottom:0.4rem;">
        <label style="font-size:0.75rem; font-weight:bold; color:#666; display:block; margin-bottom:0.15rem;">画面标签文字：</label>
        <input type="text" value="${escHtml(visibleText)}" placeholder="标签文本" style="font-size:0.85rem; padding:4px 6px;" onchange="updateMaskBoxField(${idx}, 'text_label', this.value)">
      </div>
      ${visualAnchor ? `
      <div style="margin-bottom:0.4rem; font-size:0.8rem; color:#555; background:#f9f9f9; padding:4px 8px; border-radius:4px; border:1px dashed #ddd;">
        <strong>视觉描述：</strong>${escHtml(visualAnchor)}
      </div>` : ''}
      ${spokenText ? `
      <div style="margin-bottom:0.4rem; font-size:0.8rem; color:#444; background:#f5faff; padding:4px 8px; border-radius:4px; border:1px dashed #c0d5ec; line-height:1.4;">
        <strong>🎙️ 演讲旁白：</strong>${escHtml(spokenText)}
      </div>` : ''}
      <div style="display:flex; gap:0.6rem; font-size:0.75rem; color:#666; margin-top:0.2rem;">
        <span>X: ${Math.round(coords[0])}</span>
        <span>Y: ${Math.round(coords[1])}</span>
        <span>宽: ${width}</span>
        <span>高: ${height}</span>
      </div>
    `;
    
    item.addEventListener('click', () => {
      state.canvasState.selectedBoxIndex = idx;
      redrawCanvas();
      // 避免重复渲染导致输入框失焦，但要把高亮表现出来
      document.querySelectorAll('#step5-boxes-list > div').forEach((el, elIdx) => {
        el.style.borderWidth = elIdx === idx ? '3px' : '2px';
        el.style.backgroundColor = elIdx === idx ? '#fffde0' : '#fff';
        if (elIdx === idx) {
          el.classList.add('highlight-glow');
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
          el.classList.remove('highlight-glow');
        }
      });
    });
    
    container.appendChild(item);
    
    if (isSelected) {
      setTimeout(() => {
        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 50);
    }
  });
}

window.deleteMaskBox = function(idx) {
  state.canvasState.boxes.splice(idx, 1);
  state.canvasState.selectedBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
};

window.updateMaskBoxField = function(idx, field, val) {
  if (state.canvasState.boxes[idx]) {
    state.canvasState.boxes[idx][field] = val;
  }
};

// Canvas 的拖拽与大小缩放事件实现
function initCanvasEvents() {
  const canvas = document.getElementById('step5-canvas');
  
  // 移除旧事件（利用 cloneNode）
  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  
  newCanvas.addEventListener('mousedown', (e) => handleCanvasMouseDown(e, newCanvas));
  newCanvas.addEventListener('mousemove', (e) => handleCanvasMouseMove(e, newCanvas));
  newCanvas.addEventListener('mouseup', handleCanvasMouseUp);
  
  // 双击空白处新增标注框
  newCanvas.addEventListener('dblclick', (e) => handleCanvasDblClick(e, newCanvas));
}

function getCanvasCoords(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (1920 / rect.width);
  const y = (e.clientY - rect.top) * (1080 / rect.height);
  return { x, y };
}

function handleCanvasMouseDown(e, canvas) {
  const { x, y } = getCanvasCoords(e, canvas);
  const handleSize = 15; // 触发手柄的绝对大小范围
  
  // 倒序检查是否有点击了边角拉手
  for (let i = state.canvasState.boxes.length - 1; i >= 0; i--) {
    const box = state.canvasState.boxes[i].box;
    const [x1, y1, x2, y2] = box;
    
    // 四角坐标
    const corners = {
      nw: { x: x1, y: y1 },
      ne: { x: x2, y: y1 },
      se: { x: x2, y: y2 },
      sw: { x: x1, y: y2 }
    };
    
    // 检查是否在四角手柄上
    for (let handle in corners) {
      const p = corners[handle];
      if (Math.abs(x - p.x) < handleSize && Math.abs(y - p.y) < handleSize) {
        state.canvasState.draggedBoxIndex = i;
        state.canvasState.draggedHandle = handle;
        state.canvasState.selectedBoxIndex = i;
        state.canvasState.startX = x;
        state.canvasState.startY = y;
        renderStep5BoxesForm();
        redrawCanvas();
        return;
      }
    }
    
    // 检查是否在矩形框内（移动整体）
    if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
      state.canvasState.draggedBoxIndex = i;
      state.canvasState.draggedHandle = 'move';
      state.canvasState.selectedBoxIndex = i;
      state.canvasState.startX = x;
      state.canvasState.startY = y;
      renderStep5BoxesForm();
      redrawCanvas();
      return;
    }
  }
  
  // 点击空白：启动十字针拉框绘制模式 (Drawing Mode)
  state.canvasState.isDrawing = true;
  state.canvasState.startX = x;
  state.canvasState.startY = y;
  state.canvasState.drawingBox = [x, y, x, y];
  
  state.canvasState.selectedBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
}

function handleCanvasMouseMove(e, canvas) {
  const { x, y } = getCanvasCoords(e, canvas);

  // 1. 绘图模式
  if (state.canvasState.isDrawing) {
    const startX = state.canvasState.startX;
    const startY = state.canvasState.startY;
    state.canvasState.drawingBox = [
      Math.min(startX, x),
      Math.min(startY, y),
      Math.max(startX, x),
      Math.max(startY, y)
    ];
    redrawCanvas();
    return;
  }

  // 2. 拖动或调整大小
  if (state.canvasState.draggedBoxIndex === -1) return;
  
  const idx = state.canvasState.draggedBoxIndex;
  const box = state.canvasState.boxes[idx].box;
  const dx = x - state.canvasState.startX;
  const dy = y - state.canvasState.startY;
  
  let [x1, y1, x2, y2] = box;
  
  if (state.canvasState.draggedHandle === 'move') {
    x1 += dx;
    x2 += dx;
    y1 += dy;
    y2 += dy;
  } else if (state.canvasState.draggedHandle === 'nw') {
    x1 += dx;
    y1 += dy;
  } else if (state.canvasState.draggedHandle === 'ne') {
    x2 += dx;
    y1 += dy;
  } else if (state.canvasState.draggedHandle === 'se') {
    x2 += dx;
    y2 += dy;
  } else if (state.canvasState.draggedHandle === 'sw') {
    x1 += dx;
    y2 += dy;
  }
  
  // 边界保护与排序纠错
  if (x1 < 0) x1 = 0;
  if (y1 < 0) y1 = 0;
  if (x2 > 1920) x2 = 1920;
  if (y2 > 1080) y2 = 1080;
  
  // 只有当坐标合法时才真正修改
  if (x2 > x1 && y2 > y1) {
    state.canvasState.boxes[idx].box = [x1, y1, x2, y2];
    state.canvasState.startX = x;
    state.canvasState.startY = y;
    redrawCanvas();
  }
}

function handleCanvasMouseUp() {
  if (state.canvasState.isDrawing) {
    state.canvasState.isDrawing = false;
    const dBox = state.canvasState.drawingBox;
    if (dBox) {
      const w = dBox[2] - dBox[0];
      const h = dBox[3] - dBox[1];
      if (w > 15 && h > 15) {
        const newBox = {
          group_id: `custom_group_${state.canvasState.boxes.length + 1}`,
          role: "content_body",
          text_label: "未命名标注",
          box: [dBox[0], dBox[1], dBox[2], dBox[3]]
        };
        state.canvasState.boxes.push(newBox);
        state.canvasState.selectedBoxIndex = state.canvasState.boxes.length - 1;
      }
    }
    state.canvasState.drawingBox = null;
    redrawCanvas();
    renderStep5BoxesForm();
    return;
  }

  state.canvasState.draggedBoxIndex = -1;
  state.canvasState.draggedHandle = null;
  renderStep5BoxesForm();
}

function handleCanvasDblClick(e, canvas) {
  const { x, y } = getCanvasCoords(e, canvas);
  // 新建默认 200x120 像素的框
  const newBox = {
    group_id: `custom_group_${state.canvasState.boxes.length + 1}`,
    role: "content_body",
    text_label: "未命名标注",
    box: [x - 100, y - 60, x + 100, y + 60]
  };
  state.canvasState.boxes.push(newBox);
  state.canvasState.selectedBoxIndex = state.canvasState.boxes.length - 1;
  redrawCanvas();
  renderStep5BoxesForm();
}

// 在 Canvas 上绘制简约线稿框图层
function redrawCanvas() {
  const canvas = document.getElementById('step5-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  
  state.canvasState.boxes.forEach((item, idx) => {
    const [x1, y1, x2, y2] = item.box;
    const isSelected = idx === state.canvasState.selectedBoxIndex;
    
    // 描边与线条设置：工整线稿风格
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.strokeStyle = isSelected ? '#111111' : '#666666';
    ctx.lineJoin = 'miter';
    
    // 用虚线表示动画未锁定，选中时为实线
    ctx.setLineDash(isSelected ? [] : [8, 4]);
    
    // 绘制工整圆角矩形
    ctx.beginPath();
    ctx.roundRect(x1, y1, x2 - x1, y2 - y1, 8);
    ctx.stroke();
    
    // 填充轻微半透明底色，强化区域感
    ctx.fillStyle = isSelected ? 'rgba(249, 214, 92, 0.06)' : 'rgba(17, 17, 17, 0.01)';
    ctx.fill();
    
    // 在左上角画规范的序号气泡：黄色实心圆形
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(x1, y1, 16, 0, Math.PI * 2);
    ctx.fillStyle = '#FFF9DB';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#111111';
    ctx.stroke();
    
    // 气泡内文字：序列号
    ctx.fillStyle = '#111111';
    ctx.font = '500 18px Inter, Noto Sans SC';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(idx + 1, x1, y1);
    
    // 绘制标签名字
    ctx.fillStyle = '#111111';
    ctx.font = '500 16px Inter, Noto Sans SC';
    ctx.textAlign = 'left';
    ctx.fillText(item.text_label || item.group_id, x1 + 22, y1 + 5);
    
    // 若当前被选中，绘制四个角的小圆形极简拉手
    if (isSelected) {
      ctx.fillStyle = '#FFFDF7';
      ctx.strokeStyle = '#111111';
      ctx.lineWidth = 2;
      const handles = [
        [x1, y1], [x2, y1], [x2, y2], [x1, y2]
      ];
      handles.forEach(h => {
        ctx.beginPath();
        ctx.arc(h[0], h[1], 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
    }
  });

  // 如果正在绘制，画出临时的虚线框
  if (state.canvasState.isDrawing && state.canvasState.drawingBox) {
    const [x1, y1, x2, y2] = state.canvasState.drawingBox;
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#111111';
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.roundRect(x1, y1, x2 - x1, y2 - y1, 6);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function saveStep5CurrentState() {
  const slide = manifestData.slides[state.activeSlideIndex];
  if (slide) {
    slide.reveal_boxes = JSON.parse(JSON.stringify(state.canvasState.boxes));
  }
}

async function runStep5AutoMask() {
  saveStep5CurrentState();
  showToast('🤖 正在调用 Vision API 进行自动框选与自适应对齐修剪，这可能需要大约 10 秒...');
  
  // 将当前的临时 manifest 存盘
  await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
  
  // 发起自动标注
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/5/auto-mask`);
  if (res.success) {
    const icon = res.vision_used ? '🔍' : '✏️';
    showToast(`${icon} ${res.message || '智能标注完成！已加载最新的目标包围框。'}`);
    loadStep5Data();
  }
}

async function saveStep5Masks() {
  saveStep5CurrentState();
  
  // 标记当前 Slide 状态为已完成
  const currentSlide = manifestData.slides[state.activeSlideIndex];
  if (currentSlide) {
    currentSlide.status = "completed";
  }
  
  showToast('💾 正在保存当前标注坐标并为您自动裁剪图层...');
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
  if (res.success) {
    showToast('🎉 标注图层保存并重建成功！');
    renderStep5Workspace(); // 重新绘制切换栏以更新已标注绿色状态
  }
}

// ==================== 步骤 6: 演讲稿编辑 ====================

let narrationData = null;

async function loadStep6Data() {
  // 获取标注的 manifest 以供左侧 Canvas 框线显示参考
  const manifestRes = await API.get(`/api/projects/${state.currentProject.id}/steps/5/result`);
  if (manifestRes.success) {
    manifestData = manifestRes.manifest;
  }

  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/6/result`);
  if (res.success && res.beats) {
    narrationData = res.beats;
    renderStep6Workspace();
  } else {
    // 首次进入没有演讲稿，提示同步初始化
    initStep6Narration();
  }
}

async function initStep6Narration() {
  showToast('📝 正在根据视觉合约自动初始化演讲稿旁白文本...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/init`);
  if (res.success) {
    narrationData = res.beats;
    renderStep6Workspace();
  }
}

function renderStep6Workspace() {
  const thumbsContainer = document.getElementById('step6-thumbs');
  thumbsContainer.innerHTML = '';
  
  narrationData.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card ${idx === state.activeSlideIndex ? 'active' : ''}`;
    const url = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    thumb.innerHTML = `
      <div class="img-preview"><img src="${url}"></div>
      <div class="slide-num">${slide.slide_id}</div>
    `;
    thumb.addEventListener('click', () => {
      saveStep6CurrentState();
      state.activeSlideIndex = idx;
      renderStep6Workspace();
    });
    thumbsContainer.appendChild(thumb);
  });
  
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide) {
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    document.getElementById('step6-bg-img').src = imgUrl;
    
    // 初始化只读 Canvas 用来在鼠标划过右侧旁白段落时高亮显示对应的 Mask 区域
    drawStep6StaticCanvas(-1);
    
    // 渲染右侧的段落列表
    const container = document.getElementById('step6-beats-list');
    container.innerHTML = '';
    
    slide.beats.forEach((beat, idx) => {
      const row = document.createElement('div');
      row.className = 'sketch-dashed';
      row.id = `step6-beat-card-${idx}`;
      row.style.padding = '0.5rem';
      row.style.backgroundColor = '#fff';
      row.innerHTML = `
        <div style="display:flex; justify-content:space-between; margin-bottom:0.2rem; font-size:0.85rem; font-weight:bold;">
          <span>句段 ${idx + 1} (${beat.group_id} - ${beat.visible_anchor})</span>
          <span style="color:#888;">意图: ${beat.spoken_intent}</span>
        </div>
        <textarea rows="2" style="font-size:0.95rem; width:100%;" onchange="updateNarrationBeatText(${idx}, this.value)">${beat.spoken_text}</textarea>
      `;
      
      // 鼠标划入该旁白，高亮左图对应的 Mask
      row.addEventListener('mouseenter', () => {
        row.classList.add('highlight-glow');
        row.style.backgroundColor = '#fffde0';
        // 查找对应 group_id 的坐标索引
        const mSlide = manifestData.slides.find(s => s.slide_id === slide.slide_id);
        if (mSlide) {
          const boxIdx = mSlide.reveal_boxes.findIndex(b => b.group_id === beat.group_id);
          drawStep6StaticCanvas(boxIdx);
        }
      });
      
      row.addEventListener('mouseleave', () => {
        row.classList.remove('highlight-glow');
        row.style.backgroundColor = '#fff';
        drawStep6StaticCanvas(-1);
      });
      
      container.appendChild(row);
    });
    
    // 给步骤 6 的 canvas 绑定鼠标移动事件，实现反向高亮与平滑滚动
    const canvas = document.getElementById('step6-canvas');
    const newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    
    newCanvas.addEventListener('mousemove', (e) => {
      const { x, y } = getCanvasCoords(e, newCanvas);
      const currentSlideId = narrationData.slides[state.activeSlideIndex].slide_id;
      const mSlide = manifestData.slides.find(s => s.slide_id === currentSlideId);
      if (!mSlide) return;
      
      let foundBoxIdx = -1;
      // 倒序检查碰撞
      for (let i = mSlide.reveal_boxes.length - 1; i >= 0; i--) {
        const box = mSlide.reveal_boxes[i].box;
        if (x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3]) {
          foundBoxIdx = i;
          break;
        }
      }
      
      // 高亮 Canvas
      drawStep6StaticCanvas(foundBoxIdx);
      
      // 反向高亮右侧列表卡片并滚动到可视区域
      slide.beats.forEach((beat, bIdx) => {
        const el = document.getElementById(`step6-beat-card-${bIdx}`);
        if (!el) return;
        
        if (foundBoxIdx !== -1 && beat.group_id === mSlide.reveal_boxes[foundBoxIdx].group_id) {
          el.classList.add('highlight-glow');
          el.style.backgroundColor = '#fffde0';
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
          el.classList.remove('highlight-glow');
          el.style.backgroundColor = '#fff';
        }
      });
    });
    
    newCanvas.addEventListener('mouseleave', () => {
      drawStep6StaticCanvas(-1);
      slide.beats.forEach((beat, bIdx) => {
        const el = document.getElementById(`step6-beat-card-${bIdx}`);
        if (el) {
          el.classList.remove('highlight-glow');
          el.style.backgroundColor = '#fff';
        }
      });
    });
  }
}

function updateNarrationBeatText(idx, val) {
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide && slide.beats[idx]) {
    slide.beats[idx].spoken_text = val;
  }
}

function drawStep6StaticCanvas(highlightIdx) {
  const canvas = document.getElementById('step6-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  
  const currentSlideId = narrationData.slides[state.activeSlideIndex].slide_id;
  const mSlide = manifestData.slides.find(s => s.slide_id === currentSlideId);
  if (!mSlide) return;
  
  mSlide.reveal_boxes.forEach((item, idx) => {
    const [x1, y1, x2, y2] = item.box;
    const isHighlighted = idx === highlightIdx;
    
    ctx.lineWidth = isHighlighted ? 3 : 2;
    ctx.strokeStyle = isHighlighted ? '#e5b922' : '#777777';
    ctx.lineJoin = 'miter';
    
    // 绘制工整圆角框
    ctx.beginPath();
    ctx.roundRect(x1, y1, x2 - x1, y2 - y1, 8);
    ctx.stroke();
    
    if (isHighlighted) {
      // 绘制雅致浅黄色半透明高亮遮罩
      ctx.fillStyle = 'rgba(249, 214, 92, 0.08)';
      ctx.fill();
    } else {
      ctx.fillStyle = 'rgba(17, 17, 17, 0.01)';
      ctx.fill();
    }
    
    // 气泡：正圆
    ctx.beginPath();
    ctx.arc(x1, y1, 14, 0, Math.PI * 2);
    ctx.fillStyle = isHighlighted ? '#FFF9DB' : '#f3f4f6';
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = '#111111';
    ctx.stroke();
    
    ctx.fillStyle = '#111111';
    ctx.font = '500 15px Inter, Noto Sans SC';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(idx + 1, x1, y1);
  });
}

function saveStep6CurrentState() {
  // 辅助防错
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide) {
    const list = document.getElementById('step6-beats-list');
    if (list) {
      const textareas = list.querySelectorAll('textarea');
      textareas.forEach((ta, idx) => {
        if (slide.beats[idx]) {
          slide.beats[idx].spoken_text = ta.value;
        }
      });
    }
  }
}

async function saveStep6Narration() {
  saveStep6CurrentState();
  showToast('💾 正在保存并校验旁白信息...');
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/6/result`, narrationData);
  if (res.success) {
    showToast('🎉 演讲旁白修改保存成功！');
  }
}

// ==================== 步骤 7: 语音合成 ====================

async function loadStep7Data() {
  // 检查是否已经合成过音频
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
  if (res.success) {
    const container = document.getElementById('step7-audio-list');
    container.innerHTML = '';
    
    res.images.forEach(img => {
      const row = document.createElement('div');
      row.className = 'sketch-dashed';
      row.style.padding = '0.8rem';
      row.style.display = 'flex';
      row.style.alignItems = 'center';
      row.style.justifyContent = 'space-between';
      row.style.backgroundColor = '#fff';
      
      const audioUrl = `/api/projects/${state.currentProject.id}/slides/${img.slide_id}/audio`;
      
      row.innerHTML = `
        <span style="font-weight:bold;">${img.slide_id}</span>
        <audio controls src="${audioUrl}" style="height:35px;"></audio>
      `;
      container.appendChild(row);
    });
    
    // 如果有图片状态，展示列表，默认隐藏 loading 状态
    document.getElementById('step7-result-box').style.display = 'block';
  }
}

async function runStep7TTS() {
  document.getElementById('step7-loading').style.display = 'block';
  document.getElementById('step7-btn-synthesize').disabled = true;
  showToast('🔊 正在调用 MiniMax TTS 服务并绑定 Reveal 关键帧时间轴...');
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/synthesize`);
    if (res.success) {
      showToast('🎉 合成并绑定时间轴完成！');
      loadStep7Data();
    }
  } catch(e) {
  } finally {
    document.getElementById('step7-loading').style.display = 'none';
    document.getElementById('step7-btn-synthesize').disabled = false;
  }
}

// ==================== 步骤 8: 视频合成与渲染 ====================

async function loadStep8Data() {
  // 检查是否有渲染出的 MP4
  const videoUrl = `/api/projects/${state.currentProject.id}/video`;
  try {
    const response = await fetch(videoUrl, { method: 'HEAD' });
    if (response.ok) {
      showStep8VideoResult(videoUrl);
    } else {
      document.getElementById('step8-result-box').style.display = 'none';
      document.getElementById('step8-btn-render').style.display = 'inline-flex';
    }
  } catch (e) {
    document.getElementById('step8-result-box').style.display = 'none';
  }
}

async function runStep8Render() {
  document.getElementById('step8-loading').style.display = 'block';
  document.getElementById('step8-btn-render').disabled = true;
  showToast('🎬 Remotion 渲染进程已启动，请稍候片刻...');
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/8/render`);
    if (res.success) {
      showToast('🎉 视频渲染成功！');
      const videoUrl = `/api/projects/${state.currentProject.id}/video`;
      showStep8VideoResult(videoUrl);
    }
  } catch(e) {
  } finally {
    document.getElementById('step8-loading').style.display = 'none';
    document.getElementById('step8-btn-render').disabled = false;
  }
}

function showStep8VideoResult(videoUrl) {
  document.getElementById('step8-btn-render').style.display = 'none';
  const player = document.getElementById('step8-video-player');
  player.src = videoUrl + `?t=${Date.now()}`;
  
  const dlBtn = document.getElementById('step8-btn-download');
  dlBtn.href = videoUrl;
  
  document.getElementById('step8-result-box').style.display = 'block';
}
