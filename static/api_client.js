// Shared authenticated JSON/FormData transport for the classic frontend.
// UI error presentation remains delegated to the shared showToast contract.

const API = {
  // 请求超时（毫秒）。LLM/TTS 等长任务后端有较长超时，但前端不能无限等待，
  // 否则用户得不到失败反馈、界面卡死。超过此时间用 AbortSignal 中断请求。
  REQUEST_TIMEOUT_MS: 120000,

  async fetch(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(
      () => controller.abort(),
      options.timeoutMs || this.REQUEST_TIMEOUT_MS
    );
    try {
      const method = String(options.method || 'GET').toUpperCase();
      const headers = new Headers(options.headers || {});
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        headers.set('X-PPT-Studio-Request', '1');
      }
      const response = await fetch(url, {
        ...options,
        headers,
        signal: options.signal || controller.signal
      });
      const contentType = response.headers.get('content-type') || '';
      const rawText = await response.text();
      let data = {};
      if (rawText) {
        if (contentType.includes('application/json')) {
          try {
            data = JSON.parse(rawText);
          } catch (e) {
            data = { detail: response.statusText || '请求失败' };
          }
        } else {
          // 非 JSON 响应（如 HTML 错误页）只展示状态摘要，避免把内部
          // 堆栈/路径直接展示给用户造成信息泄露。
          data = { detail: `HTTP ${response.status} ${response.statusText || '请求失败'}` };
        }
      }
      if (!response.ok) {
        const detail = data.detail || data.message || response.statusText || '请求失败';
        const message = typeof detail === 'string'
          ? detail
          : (detail?.message || JSON.stringify(detail));
        throw new Error(message);
      }
      return data;
    } catch (error) {
      if (error && error.name === 'AbortError') {
        showToast(`❌ 请求超时（${Math.round((options.timeoutMs || this.REQUEST_TIMEOUT_MS) / 1000)}秒），请重试`);
        throw new Error('请求超时');
      }
      showToast(`❌ 错误: ${error.message}`);
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  },

  async get(url) {
    return this.fetch(url);
  },

  async post(url, body, extra = {}) {
    const isFormData = body instanceof FormData;
    return this.fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' },
      ...extra
    });
  },

  async put(url, body, extra = {}) {
    return this.fetch(url, {
      method: 'PUT',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
      ...extra
    });
  },

  async delete(url) {
    return this.fetch(url, { method: 'DELETE' });
  }
};

window.API = API;
