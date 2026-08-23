// Digital Human Panel - 数字人讲解配置面板（上传形式 + 圆形窗口三向自定义）
// 三向自定义：
//   ① 圆内拖动 = 调整视频与框的相对位置（video.ox/oy）
//   ② 右下角手柄拖动 = 调整框大小（circle.r）
//   ③ 圆外拖动 = 调整框在页面上的位置（circle.cx/cy）
// 依赖全局 API / state / showToast / escHtml

(function () {
  "use strict";

  var PROJECT_PREFIX = "/api/projects";

  var dhState = {
    config: {
      enabled: false,
      mode: "comfyui",          // 'comfyui' | 'upload'
      shape: "circle",
      avatar_id: "",
      circle: { cx: 0.8, cy: 0.2, r: 0.25 },
      video: { ox: 0.5, oy: 0.5, zoom: 1.0 },
      slides: {},
    },
    audioReady: {},
    polling: {},
    uploadVideoExists: false,
    videoSize: null, // {w,h} 预览视频原始尺寸
    comfyuiWorkflowExists: false,
    avatarUploaded: false,
  };

  function projectId() {
    return (state && state.currentProject && state.currentProject.id) || null;
  }

  function base() {
    return PROJECT_PREFIX + "/" + projectId() + "/digital-human";
  }

  // ---------------- 加载与保存配置 ----------------

  async function loadConfig() {
    var pid = projectId();
    if (!pid) return;
    try {
      var res = await API.get(base() + "/config");
      if (res && res.config) {
        dhState.config = res.config;
        if (!dhState.config.circle) dhState.config.circle = { cx: 0.8, cy: 0.2, r: 0.25 };
        if (!dhState.config.video) dhState.config.video = { ox: 0.5, oy: 0.5, zoom: 1.0 };
        if (dhState.config.shape !== "rect") dhState.config.shape = "circle";
      }
      // 应用全局固定布局（如有），覆盖项目值为用户固定的全局默认
      applyFixedLayout();
      if (res && res.audio_ready) dhState.audioReady = res.audio_ready;
      if (res && res.audio_ready_count !== undefined) dhState.audioReadyCount = res.audio_ready_count;
      if (res && res.total_slides !== undefined) dhState.totalSlides = res.total_slides;
      if (res && res.slides) {
        dhState.config.slides = res.slides;
      }
      dhState.uploadVideoExists = !!(res && res.upload_video_exists);
      dhState.avatarUploaded = !!dhState.config.avatar_id;
      updateAudioStatus();
      applyConfigToUI();
      checkComfyuiWorkflow();
      loadPreview();
      // 恢复未完成 job 的轮询（页面刷新后）
      if (dhState.config.slides) {
        Object.keys(dhState.config.slides).forEach(function (slideId) {
          var slide = dhState.config.slides[slideId];
          if (slide && slide.job_id &&
              (slide.status === "queued" || slide.status === "processing")) {
            pollJob(slideId, slide.job_id);
          }
        });
      }
      if (typeof window.__dhMarkEnabled === "function") {
        window.__dhMarkEnabled(!!dhState.config.enabled);
      }
    } catch (e) {
      console.error("[DH] loadConfig failed:", e);
    }
  }

  function applyConfigToUI() {
    var enabledEl = document.getElementById("dh-enabled");
    var body = document.getElementById("dh-panel-body");
    if (enabledEl) enabledEl.checked = !!dhState.config.enabled;
    if (body) body.style.display = dhState.config.enabled ? "" : "none";
    // 形状切换高亮
    document.querySelectorAll("[data-dh-shape]").forEach(function (btn) {
      var active = btn.getAttribute("data-dh-shape") === (dhState.config.shape || "circle");
      btn.classList.toggle("dh-shape-active", active);
    });
    // 模式选项卡
    updateModeTabs();
    // 上传视频状态
    var uploadStatus = document.getElementById("dh-upload-video-status");
    if (uploadStatus) {
      uploadStatus.textContent = dhState.uploadVideoExists ? "已上传" : "未上传";
      uploadStatus.style.color = dhState.uploadVideoExists ? "#4CAF50" : "";
    }
    // 形象图片状态
    var avatarStatus = document.getElementById("dh-comfyui-avatar-status");
    if (avatarStatus) {
      if (dhState.avatarUploaded) {
        avatarStatus.textContent = "已上传";
        avatarStatus.style.color = "#4CAF50";
      } else {
        avatarStatus.textContent = "未上传形象图片";
        avatarStatus.style.color = "";
      }
    }
    applyCircleToPreview();
  }

  function updateModeTabs() {
    var mode = dhState.config.mode || "comfyui";
    var tabComfyui = document.getElementById("dh-tab-comfyui");
    var tabUpload = document.getElementById("dh-tab-upload");
    var panelComfyui = document.getElementById("dh-mode-panel-comfyui");
    var panelUpload = document.getElementById("dh-mode-panel-upload");
    if (tabComfyui) tabComfyui.classList.toggle("dh-tab-active", mode === "comfyui");
    if (tabUpload) tabUpload.classList.toggle("dh-tab-active", mode === "upload");
    if (panelComfyui) panelComfyui.style.display = mode === "comfyui" ? "" : "none";
    if (panelUpload) panelUpload.style.display = mode === "upload" ? "" : "none";
  }

  function switchMode(mode) {
    dhState.config.mode = mode;
    updateModeTabs();
    saveConfig();
  }

  async function saveConfig() {
    var pid = projectId();
    if (!pid) return;
    var enabledEl = document.getElementById("dh-enabled");
    dhState.config.enabled = enabledEl ? enabledEl.checked : false;
    dhState.config.mode = dhState.config.mode || "comfyui";
    try {
      await API.put(base() + "/config", {
        enabled: dhState.config.enabled,
        mode: dhState.config.mode,
        shape: dhState.config.shape || "circle",
        avatar_id: dhState.config.avatar_id,
        circle: dhState.config.circle,
        video: dhState.config.video,
      });
      showToast("数字人讲解设置已保存");
      if (typeof window.__dhMarkEnabled === "function") {
        window.__dhMarkEnabled(!!dhState.config.enabled);
      }
    } catch (e) {
      console.error("[DH] saveConfig failed:", e);
    }
  }

  // ---------------- 服务状态 ----------------

  async function loadHealth() {
    var el = document.getElementById("dh-service-status");
    if (!el) return;
    if (!projectId()) return;  // 首页无选中项目时跳过，避免 404 "项目不存在"
    try {
      var res = await API.get(base() + "/health");
      if (res) {
        if (res.model_ready) {
          el.textContent = res.comfyui_online ? "模型就绪（ComfyUI）" : "模型就绪";
          el.className = "dh-service-status dh-ok";
        } else {
          el.textContent = res.comfyui_online ? "ComfyUI 在线" : "模型未就绪";
          el.className = "dh-service-status dh-warn";
        }
      } else {
        el.textContent = "模型状态未知";
        el.className = "dh-service-status dh-warn";
      }
    } catch (e) {
      el.textContent = "数字人服务未启动（需先启动 :9001）";
      el.className = "dh-service-status dh-error";
    }
  }

  // ---------------- 上传已生成视频（upload 模式） ----------------

  async function uploadDigiVideo(file) {
    if (!file) return;
    var pid = projectId();
    if (!pid) return;
    var fd = new FormData();
    fd.append("file", file);
    try {
      var res = await API.post(base() + "/upload", fd);
      if (res && res.success) {
        dhState.uploadVideoExists = true;
        dhState.config.mode = "upload";
        dhState.config.enabled = true;
        var enabledEl = document.getElementById("dh-enabled");
        if (enabledEl) enabledEl.checked = true;
        applyConfigToUI();
        showToast("数字人讲解视频已上传");
        loadPreview();
        saveConfig();
      }
    } catch (e) {
      console.error("[DH] uploadDigiVideo failed:", e);
      showToast("上传失败：" + ((e && e.message) || "未知错误"));
    }
  }

  // ---------------- 圆形窗口预览（三向自定义） ----------------

  function canvasSize() {
    var c = document.getElementById("dh-circle-canvas");
    if (!c) return { w: 640, h: 360 };
    return { w: c.clientWidth || 640, h: c.clientHeight || 360 };
  }

  function applyCircleToPreview() {
    var circle = dhState.config.circle || { cx: 0.8, cy: 0.2, r: 0.25 };
    var videoCfg = dhState.config.video || { ox: 0.5, oy: 0.5, zoom: 1.0 };
    var layer = document.getElementById("dh-circle-layer");
    var videoEl = document.getElementById("dh-preview-video");
    var handle = document.getElementById("dh-circle-resize");
    if (!layer) return;

    var c = canvasSize();
    var D = Math.max(24, circle.r * 2 * Math.min(c.w, c.h));
    var shape = dhState.config.shape === "rect" ? "rect" : "circle";
    layer.style.left = circle.cx * c.w - D / 2 + "px";
    layer.style.top = circle.cy * c.h - D / 2 + "px";
    layer.style.width = D + "px";
    layer.style.height = D + "px";
    layer.style.clipPath = shape === "rect" ? "none" : "circle(50% at 50% 50%)";
    layer.style.borderRadius = shape === "rect" ? "8px" : "50%";

    // 视频在框内 cover 缩放 + 平移（与后端 crop 逻辑一致）
    if (videoEl && dhState.videoSize) {
      var zoom = Math.max(0.5, Math.min(4, Number(videoCfg.zoom) || 1));
      var vw = dhState.videoSize.w, vh = dhState.videoSize.h;
      var sw, sh;
      if (vw >= vh) { sw = D * zoom * vw / vh; sh = D * zoom; }
      else { sw = D * zoom; sh = D * zoom * vh / vw; }
      var cropX = Math.max(0, Math.round((sw - D) * (Number(videoCfg.ox) || 0.5)));
      var cropY = Math.max(0, Math.round((sh - D) * (Number(videoCfg.oy) || 0.5)));
      videoEl.style.width = sw + "px";
      videoEl.style.height = sh + "px";
      videoEl.style.left = -cropX + "px";
      videoEl.style.top = -cropY + "px";
    } else if (videoEl) {
      videoEl.style.width = "100%";
      videoEl.style.height = "100%";
      videoEl.style.left = "0px";
      videoEl.style.top = "0px";
    }
    if (handle) {
      var handleSize = 18;
      handle.style.width = handleSize + "px";
      handle.style.height = handleSize + "px";
      // 手柄定位到圆形左上角边缘（canvas 坐标），避开 clip-path 裁剪
      handle.style.left = (circle.cx * c.w - D / 2 - handleSize / 2) + "px";
      handle.style.top = (circle.cy * c.h - D / 2 - handleSize / 2) + "px";
    }

    syncSliders(circle, videoCfg);
    var diaEl = document.getElementById("dh-info-diameter");
    var pxEl = document.getElementById("dh-info-px");
    var pyEl = document.getElementById("dh-info-py");
    if (diaEl) diaEl.textContent = Math.round(D);
    if (pxEl) pxEl.textContent = Math.round(circle.cx * c.w);
    if (pyEl) pyEl.textContent = Math.round(circle.cy * c.h);
  }

  function captureVideoFirstFrame() {
    var video = document.getElementById("dh-preview-video");
    var refBox = document.getElementById("dh-video-ref-box");
    var refImg = document.getElementById("dh-video-ref");
    if (!video || !refBox || !refImg || !video.videoWidth || !video.videoHeight) return;
    refBox.style.display = "flex";
    var done = false;
    var doDraw = function () {
      if (done) return;
      done = true;
      var w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) return;
      var cv = document.createElement("canvas");
      cv.width = w;
      cv.height = h;
      cv.getContext("2d").drawImage(video, 0, 0, w, h);
      refImg.src = cv.toDataURL("image/jpeg", 0.85);
      video.onseeked = null;
      // 恢复播放（loop 预览）
      try { video.play().catch(function () {}); } catch (e) {}
    };
    video.onseeked = doDraw;
    try { video.currentTime = 0.01; } catch (e) { doDraw(); }
    // 兜底：若 1.5s 内未触发 seeked（如非 seekable 流），直接绘制当前帧
    setTimeout(function () { if (!done) doDraw(); }, 1500);
  }

  function loadPreview() {
    var video = document.getElementById("dh-preview-video");
    if (!video) return;
    var src = null;
    var mode = dhState.config.mode || "comfyui";
    if (mode === "upload" && dhState.uploadVideoExists) {
      src = base() + "/upload/video?t=" + Date.now();
    } else {
      // 优先用整段已生成的数字人视频
      var slides = dhState.config.slides || {};
      if (slides["full"] && slides["full"].video_exists) {
        src = base() + "/slides/full/video?t=" + Date.now();
      } else {
        var firstDone = Object.keys(slides).find(function (sid) {
          return slides[sid] && slides[sid].video_exists;
        });
        if (firstDone) {
          src = base() + "/slides/" + encodeURIComponent(firstDone) + "/video?t=" + Date.now();
        }
      }
    }
    if (src) {
      // 重置 onseeked 防止旧回调干扰
      video.onseeked = null;
      video.onloadeddata = null;
      video.src = src;
      video.load();
      // 视频元数据就绪后再播放并截取第一帧
      video.onloadeddata = function () {
        captureFirstFrame(video);
        try { video.play().catch(function () {}); } catch (e) {}
      };
      // 兜底：5s 后若仍未截取，强制尝试一次
      setTimeout(function () {
        if (video.readyState >= 2) captureFirstFrame(video);
      }, 5000);
    }
  }

  // 从预览视频中抽取第一帧，显示到参考图区（dh-video-ref）
  function captureFirstFrame(video) {
    if (!video || video.readyState < 2) return;  // 需至少有当前帧数据
    try {
      var cv = document.createElement("canvas");
      var vw = video.videoWidth || 320;
      var vh = video.videoHeight || 320;
      cv.width = 320;
      cv.height = Math.round(320 * vh / Math.max(1, vw));
      var ctx = cv.getContext("2d");
      ctx.drawImage(video, 0, 0, cv.width, cv.height);
      var dataUrl = cv.toDataURL("image/jpeg", 0.85);
      var refImg = document.getElementById("dh-video-ref");
      var refBox = document.getElementById("dh-video-ref-box");
      if (refImg && dataUrl && dataUrl.length > 100) {
        refImg.src = dataUrl;
        if (refBox) refBox.style.display = "";
      }
    } catch (e) {
      console.warn("[DH] captureFirstFrame failed:", e);
    }
  }

  // ---------------- 三向拖动 ----------------

  function initCircleDrag() {
    var canvas = document.getElementById("dh-circle-canvas");
    if (!canvas || canvas.dataset.dhBound === "1") return;
    canvas.dataset.dhBound = "1";
    var dragging = null; // 'panVideo' | 'moveFrame' | 'resize'
    var last = { x: 0, y: 0 };

    function circleInfo() {
      var c = canvasSize();
      var circle = dhState.config.circle || { cx: 0.8, cy: 0.2, r: 0.25 };
      var D = Math.max(24, circle.r * 2 * Math.min(c.w, c.h));
      return { c: c, circle: circle, D: D, cx: circle.cx * c.w, cy: circle.cy * c.h };
    }

    canvas.addEventListener("pointerdown", function (e) {
      var rect = canvas.getBoundingClientRect();
      var px = e.clientX - rect.left;
      var py = e.clientY - rect.top;
      var info = circleInfo();
      var dx = px - info.cx;
      var dy = py - info.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      // 命中左上角手柄 → 调整大小
      var hx = info.cx - info.D / 2 - px;
      var hy = info.cy - info.D / 2 - py;
      if (hx <= 20 && hy <= 20 && hx >= -10 && hy >= -10 && dist > info.D * 0.4) {
        dragging = "resize";
      } else if (dist <= info.D / 2) {
        dragging = "panVideo"; // 圆内 → 平移视频
      } else {
        dragging = "moveFrame"; // 圆外 → 移动框
      }
      last.x = px;
      last.y = py;
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    canvas.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var rect = canvas.getBoundingClientRect();
      var px = e.clientX - rect.left;
      var py = e.clientY - rect.top;
      var info = circleInfo();
      var circle = info.circle;
      var videoCfg = dhState.config.video || { ox: 0.5, oy: 0.5, zoom: 1.0 };

      if (dragging === "moveFrame") {
        circle.cx = Math.min(1, Math.max(0, info.cx / info.c.w + (px - last.x) / info.c.w));
        circle.cy = Math.min(1, Math.max(0, info.cy / info.c.h + (py - last.y) / info.c.h));
      } else if (dragging === "resize") {
        var dist = Math.sqrt((px - info.cx) * (px - info.cx) + (py - info.cy) * (py - info.cy));
        circle.r = Math.min(0.6, Math.max(0.06, dist / Math.min(info.c.w, info.c.h)));
      } else if (dragging === "panVideo") {
        if (dhState.videoSize) {
          var zoom = Math.max(0.5, Math.min(4, Number(videoCfg.zoom) || 1));
          var vw = dhState.videoSize.w, vh = dhState.videoSize.h;
          var sw, sh;
          if (vw >= vh) { sw = info.D * zoom * vw / vh; sh = info.D * zoom; }
          else { sw = info.D * zoom; sh = info.D * zoom * vh / vw; }
          var maxDx = Math.max(0, sw - info.D);
          var maxDy = Math.max(0, sh - info.D);
          var scaleX = maxDx ? sw / info.D : 0; // 屏幕位移 → 视频位移比例
          var scaleY = maxDy ? sh / info.D : 0;
          var curCropX = maxDx ? (Number(videoCfg.ox) || 0.5) * maxDx : 0;
          var curCropY = maxDy ? (Number(videoCfg.oy) || 0.5) * maxDy : 0;
          curCropX = Math.min(maxDx, Math.max(0, curCropX + (px - last.x) * scaleX));
          curCropY = Math.min(maxDy, Math.max(0, curCropY + (py - last.y) * scaleY));
          videoCfg.ox = maxDx ? curCropX / maxDx : 0.5;
          videoCfg.oy = maxDy ? curCropY / maxDy : 0.5;
        }
      }
      last.x = px;
      last.y = py;
      applyCircleToPreview();
    });

    canvas.addEventListener("pointerup", function () {
      if (dragging) {
        dragging = null;
        saveConfig();
      }
    });
    canvas.addEventListener("pointercancel", function () {
      dragging = null;
    });
  }

  // ---------------- 滑块同步 ----------------

  function syncSliders(circle, videoCfg) {
    var map = [
      { s: "dh-slider-cx", v: "dh-val-cx", val: circle.cx, fmt: function (x) { return x.toFixed(2); } },
      { s: "dh-slider-cy", v: "dh-val-cy", val: circle.cy, fmt: function (x) { return x.toFixed(2); } },
      { s: "dh-slider-r", v: "dh-val-r", val: circle.r, fmt: function (x) { return x.toFixed(2); } },
      { s: "dh-slider-zoom", v: "dh-val-zoom", val: videoCfg.zoom, fmt: function (x) { return Math.round(x * 100) + "%"; } },
      { s: "dh-slider-ox", v: "dh-val-ox", val: videoCfg.ox, fmt: function (x) { return x.toFixed(2); } },
      { s: "dh-slider-oy", v: "dh-val-oy", val: videoCfg.oy, fmt: function (x) { return x.toFixed(2); } },
    ];
    map.forEach(function (m) {
      var sl = document.getElementById(m.s);
      var vl = document.getElementById(m.v);
      if (sl) sl.value = String(m.val);
      if (vl) vl.textContent = m.fmt(Number(m.val) || 0);
    });
  }

  // ---------------- 固定布局（全局默认值） ----------------

  var FIXED_KEY = "PPT_DH_FIXED_LAYOUT";

  function getFixedLayout() {
    try {
      var raw = localStorage.getItem(FIXED_KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (data && data.circle && data.video) return data;
    } catch (e) {}
    return null;
  }

  function applyFixedLayout() {
    var fixed = getFixedLayout();
    if (!fixed) return;
    dhState.config.circle = Object.assign({}, fixed.circle);
    dhState.config.video = Object.assign({}, fixed.video);
    if (fixed.shape) dhState.config.shape = fixed.shape;
  }

  function lockLayout() {
    var fixed = getFixedLayout();
    if (fixed) {
      localStorage.removeItem(FIXED_KEY);
      showToast("已解除固定布局");
    } else {
      try {
        localStorage.setItem(FIXED_KEY, JSON.stringify({
          circle: dhState.config.circle,
          video: dhState.config.video,
          shape: dhState.config.shape,
        }));
        showToast("当前布局已固定为全局默认值");
      } catch (e) {
        showToast("固定失败：" + ((e && e.message) || "未知错误"));
      }
    }
    updateLockUI();
  }

  function updateLockUI() {
    var btn = document.getElementById("dh-btn-lock");
    var status = document.getElementById("dh-lock-status");
    var fixed = getFixedLayout();
    if (btn) {
      btn.textContent = fixed ? "解除固定" : "固定当前布局";
      btn.classList.toggle("dh-locked", !!fixed);
    }
    if (status) {
      status.textContent = fixed ? "已固定（全局生效）" : "未固定";
      status.className = "dh-lock-status " + (fixed ? "dh-lock-on" : "");
    }
  }

  // ---------------- 位置预设 / 重置（保留函数，按钮已移除） ----------------

  function setPositionPreset(key) {
    var circle = dhState.config.circle || { cx: 0.8, cy: 0.2, r: 0.25 };
    var presets = {
      right_bottom: [0.82, 0.78],
      left_bottom: [0.18, 0.78],
      right_top: [0.82, 0.22],
      left_top: [0.18, 0.22],
    };
    var pos = presets[key] || presets.right_bottom;
    circle.cx = pos[0];
    circle.cy = pos[1];
    applyCircleToPreview();
    saveConfig();
  }

  function resetCircle() {
    dhState.config.circle = { cx: 0.8, cy: 0.2, r: 0.25 };
    dhState.config.video = { ox: 0.5, oy: 0.5, zoom: 1.0 };
    applyConfigToUI();
    saveConfig();
  }

  function setShape(shape) {
    dhState.config.shape = shape === "rect" ? "rect" : "circle";
    applyConfigToUI();
    saveConfig();
  }

  // ---------------- 整段语音导出 ----------------

  async function exportFullAudio() {
    var pid = projectId();
    if (!pid) return;
    var btn = document.getElementById("dh-btn-export-audio");
    var statusEl = document.getElementById("dh-audio-export-status");
    if (btn) { btn.disabled = true; }
    if (statusEl) statusEl.textContent = "导出中...";
    try {
      var res = await API.post(base() + "/export-audio", { gap_sec: 0.6 }, { timeout: 900000 });
      if (res && res.success) {
        var mins = res.duration_sec ? (res.duration_sec / 60).toFixed(1) : "?";
        if (statusEl) statusEl.textContent = "已导出 " + res.slides + " 页，时长约 " + mins + " 分钟";
        // 触发下载
        var a = document.createElement("a");
        a.href = res.url;
        a.download = "course_audio_full.mp3";
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else if (res && res.detail) {
        if (statusEl) statusEl.textContent = "导出失败";
        showToast(res.detail);
      }
    } catch (e) {
      console.error("[DH] exportFullAudio failed:", e);
      if (statusEl) statusEl.textContent = "导出失败";
      showToast("导出失败：" + ((e && (e.detail || e.message)) || "未知错误"));
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ---------------- 生成（ComfyUI） ----------------

  function audioReadySlides() {
    return Object.keys(dhState.audioReady || {}).filter(function (sid) {
      return dhState.audioReady[sid];
    });
  }

  function updateAudioStatus() {
    var el = document.getElementById("dh-slide-status");
    if (!el) return;
    var ready = dhState.audioReadyCount || 0;
    var total = dhState.totalSlides || 0;
    var slides = dhState.config.slides || {};
    var labels = { queued: "排队中", processing: "生成中", done: "完成", failed: "失败" };

    // 优先显示整段数字人生成状态
    var fullItem = slides["full"];
    if (fullItem && fullItem.status) {
      var fst = fullItem.status;
      var fcls = fst === "done" ? "dh-done" : fst === "failed" ? "dh-failed" : "dh-busy";
      var chips = '<span class="dh-slide-status-note">整段数字人视频</span>';
      chips += '<div style="margin-top:0.3rem;"><span class="dh-slide-chip ' + fcls + '">' +
               (labels[fst] || fst) + '</span></div>';
      if (fst === "done" && fullItem.video_exists) {
        chips += '<div style="margin-top:0.3rem;"><span class="dh-slide-status-note" style="color:#4CAF50;">整段视频已生成，可在预览中查看</span></div>';
      }
      el.innerHTML = chips;
      return;
    }

    var chips = "";
    if (total === 0) {
      chips = '<span class="dh-slide-status-note">尚未导入文章或生成故事板</span>';
    } else if (ready === 0) {
      chips = '<span class="dh-slide-status-note">⚠️ 尚无已合成的旁白音频（0/' + total + ' 页）。请先完成第 5 步「旁白与音频」。</span>';
    } else {
      chips = '<span class="dh-slide-status-note">音频就绪：' + ready + '/' + total + ' 页（点击下方按钮将合并为一整段音频并生成单个数字人视频）</span>';
    }
    el.innerHTML = chips;
  }

  async function generateSlide(slideId) {
    var pid = projectId();
    if (!pid) return;
    if (!dhState.config.avatar_id) {
      showToast("请先上传数字人形象图片");
      return;
    }
    try {
      var res = await API.post(base() + "/generate/" + encodeURIComponent(slideId), {
        avatar_id: dhState.config.avatar_id,
      });
      if (res && res.job_id) {
        markSlideStatus(slideId, "queued");
        pollJob(slideId, res.job_id);
      } else if (res && res.detail) {
        showToast(res.detail);
      }
    } catch (e) {
      console.error("[DH] generate failed:", e);
    }
  }

  function markSlideStatus(slideId, status) {
    if (!dhState.config.slides) dhState.config.slides = {};
    dhState.config.slides[slideId] = Object.assign({}, dhState.config.slides[slideId], { status: status });
    updateAudioStatus();
  }

  async function pollJob(slideId, jobId) {
    if (dhState.polling[jobId]) return;
    dhState.polling[jobId] = true;
    var label = slideId === "full" ? "整段" : "页面 " + slideId;
    try {
      for (var i = 0; i < 3600; i++) {
        await sleep(2000);
        var res = await API.get(base() + "/jobs/" + encodeURIComponent(jobId));
        var job = res && res.job ? res.job : res;
        var status = job && job.status;
        if (status === "done") {
          markSlideStatus(slideId, "done");
          // 标记视频已存在，使 loadPreview 能定位到视频源
          if (!dhState.config.slides) dhState.config.slides = {};
          if (!dhState.config.slides[slideId]) dhState.config.slides[slideId] = {};
          dhState.config.slides[slideId].video_exists = true;
          updateAudioStatus();
          loadPreview();
          showToast(label + " 数字人已生成");
          break;
        } else if (status === "failed") {
          markSlideStatus(slideId, "failed");
          showToast(label + " 生成失败：" + ((job && job.error) || "未知错误"));
          break;
        } else if (status === "unavailable") {
          markSlideStatus(slideId, "failed");
          showToast("该任务不可用，请确认模型与服务状态");
          break;
        } else {
          markSlideStatus(slideId, status || "processing");
        }
      }
    } catch (e) {
      console.error("[DH] pollJob failed:", e);
      markSlideStatus(slideId, "failed");
    } finally {
      dhState.polling[jobId] = false;
    }
  }

  async function generateAll() {
    var pid = projectId();
    if (!pid) return;
    if (!dhState.config.avatar_id) {
      showToast("请先上传数字人形象图片");
      return;
    }
    if (!dhState.comfyuiWorkflowExists) {
      showToast("请先上传 ComfyUI 工作流 JSON");
      return;
    }
    var ready = dhState.audioReadyCount || 0;
    var total = dhState.totalSlides || 0;
    if (!ready) {
      showToast("尚无已合成的旁白音频（0/" + total + " 页），请先完成音频合成");
      return;
    }

    var btn = document.getElementById("dh-btn-generate-all");
    if (btn) btn.disabled = true;

    try {
      // 第一步：确保整段音频已导出（合并 5 页音频 + 页间静音）
      var statusEl = document.getElementById("dh-slide-status");
      if (statusEl) statusEl.innerHTML = '<span class="dh-slide-status-note">正在合并 ' + ready + ' 页音频...</span>';
      var exportRes = await API.post(base() + "/export-audio", { gap_sec: 0.6 }, { timeout: 900000 });
      if (!exportRes || !exportRes.success) {
        showToast((exportRes && exportRes.detail) || "导出整段语音失败");
        updateAudioStatus();
        return;
      }

      // 第二步：使用整段音频创建单个数字人生成任务
      if (statusEl) statusEl.innerHTML = '<span class="dh-slide-status-note">正在提交数字人生成任务...</span>';
      var res = await API.post(base() + "/generate-full", {
        avatar_id: dhState.config.avatar_id,
      });
      if (res && res.job_id) {
        markSlideStatus("full", "queued");
        pollJob("full", res.job_id);
        showToast("已提交整段数字人生成任务（" + exportRes.slides + " 页音频已合并）。Wan2.2 S2V 生成耗时较长，请耐心等待。");
      } else if (res && res.detail) {
        showToast(res.detail);
        updateAudioStatus();
      }
    } catch (e) {
      console.error("[DH] generateAll failed:", e);
      showToast("生成失败：" + ((e && (e.detail || e.message)) || "未知错误"));
      updateAudioStatus();
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // renderSlideStatus 已合并到 updateAudioStatus

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // ---------------- ComfyUI 模式 ----------------

  async function uploadComfyuiWorkflow(file) {
    if (!file) return;
    var fd = new FormData();
    fd.append("file", file);
    try {
      var res = await API.post(base() + "/comfyui/workflow", fd);
      if (res && res.success) {
        dhState.comfyuiWorkflowExists = true;
        dhState.config.mode = "comfyui";
        var statusEl = document.getElementById("dh-comfyui-workflow-status");
        if (statusEl) {
          statusEl.textContent = "已上传（" + res.nodes + " 节点）";
          statusEl.style.color = "#4CAF50";
        }
        showToast("ComfyUI 工作流已上传（" + res.nodes + " 节点）");
      }
    } catch (e) {
      console.error("[DH] uploadComfyuiWorkflow failed:", e);
      showToast("工作流上传失败：" + ((e && (e.detail || e.message)) || "未知错误"));
    }
  }

  async function checkComfyuiWorkflow() {
    try {
      var res = await API.get(base() + "/comfyui/workflow");
      if (res && res.exists) {
        dhState.comfyuiWorkflowExists = true;
        var statusEl = document.getElementById("dh-comfyui-workflow-status");
        if (statusEl) {
          statusEl.textContent = "已上传（" + (res.nodes || 0) + " 节点）";
          statusEl.style.color = "#4CAF50";
        }
      }
    } catch (e) {
      // 静默
    }
  }

  // ---------------- 初始化 ----------------

  function init() {
    var panel = document.getElementById("digital-human-panel");
    if (!panel) return;

    var enabledEl = document.getElementById("dh-enabled");
    var btnGenAll = document.getElementById("dh-btn-generate-all");
    var btnSave = document.getElementById("dh-btn-save");
    var btnLock = document.getElementById("dh-btn-lock");

    if (enabledEl) {
      enabledEl.addEventListener("change", function () {
        var body = document.getElementById("dh-panel-body");
        if (body) body.style.display = enabledEl.checked ? "" : "none";
        saveConfig();
      });
    }
    // 数值精调滑块
    var dhSliders = [
      { id: "dh-slider-cx", key: "circle", prop: "cx" },
      { id: "dh-slider-cy", key: "circle", prop: "cy" },
      { id: "dh-slider-r", key: "circle", prop: "r" },
      { id: "dh-slider-zoom", key: "video", prop: "zoom" },
      { id: "dh-slider-ox", key: "video", prop: "ox" },
      { id: "dh-slider-oy", key: "video", prop: "oy" },
    ];
    dhSliders.forEach(function (s) {
      var el = document.getElementById(s.id);
      if (!el) return;
      el.addEventListener("input", function () {
        if (!dhState.config[s.key]) return;
        dhState.config[s.key][s.prop] = Number(el.value);
        applyCircleToPreview();
      });
      el.addEventListener("change", function () {
        saveConfig();
      });
    });
    if (btnGenAll) btnGenAll.addEventListener("click", generateAll);
    if (btnSave) btnSave.addEventListener("click", saveConfig);
    if (btnLock) btnLock.addEventListener("click", lockLayout);

    // 模式选项卡切换
    var tabComfyui = document.getElementById("dh-tab-comfyui");
    var tabUpload = document.getElementById("dh-tab-upload");
    if (tabComfyui) tabComfyui.addEventListener("click", function () { switchMode("comfyui"); });
    if (tabUpload) tabUpload.addEventListener("click", function () { switchMode("upload"); });

    // 导入视频上传
    var uploadVideoFile = document.getElementById("dh-upload-video-file");
    if (uploadVideoFile) {
      uploadVideoFile.addEventListener("change", function () {
        uploadDigiVideo(uploadVideoFile.files && uploadVideoFile.files[0]);
        uploadVideoFile.value = "";
      });
    }

    // ComfyUI 工作流上传
    var wfFile = document.getElementById("dh-comfyui-workflow-file");
    if (wfFile) {
      wfFile.addEventListener("change", function () {
        uploadComfyuiWorkflow(wfFile.files && wfFile.files[0]);
        wfFile.value = "";
      });
    }

    // ComfyUI 形象图片上传（复用 avatar 上传接口，支持图片）
    var cfAvatarFile = document.getElementById("dh-comfyui-avatar-file");
    if (cfAvatarFile) {
      cfAvatarFile.addEventListener("change", function () {
        uploadAvatar(cfAvatarFile.files && cfAvatarFile.files[0]);
        cfAvatarFile.value = "";
      });
    }

    var btnExportAudio = document.getElementById("dh-btn-export-audio");
    if (btnExportAudio) btnExportAudio.addEventListener("click", exportFullAudio);
    // 第 6 步工具栏的导出按钮也复用同一逻辑
    var btnStep6Export = document.getElementById("step6-btn-export-audio");
    if (btnStep6Export) btnStep6Export.addEventListener("click", exportFullAudio);

    document.querySelectorAll("[data-dh-shape]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setShape(btn.getAttribute("data-dh-shape"));
      });
    });

    var video = document.getElementById("dh-preview-video");
    if (video) {
      video.addEventListener("loadedmetadata", function () {
        dhState.videoSize = { w: video.videoWidth || 0, h: video.videoHeight || 0 };
        applyCircleToPreview();
        captureVideoFirstFrame();
      });
      video.addEventListener("error", function () {
        dhState.videoSize = null;
      });
    }

    initCircleDrag();
    updateLockUI();
    loadHealth();
    loadConfig();
  }

  async function uploadAvatar(file) {
    if (!file) return;
    var fd = new FormData();
    fd.append("file", file);
    fd.append("name", file.name);
    try {
      var res = await API.post(base() + "/avatars", fd);
      if (res && res.avatar_id) {
        dhState.config.avatar_id = res.avatar_id;
        dhState.avatarUploaded = true;
        showToast("数字人形象图片已上传");
        applyConfigToUI();
        await saveConfig();
      }
    } catch (e) {
      console.error("[DH] uploadAvatar failed:", e);
      showToast("形象图片上传失败：" + ((e && (e.detail || e.message)) || "未知错误"));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // 步骤 8 面板显示时刷新一次
  var dhRefreshTimer = null;
  function scheduleRefresh() {
    if (dhRefreshTimer) clearTimeout(dhRefreshTimer);
    dhRefreshTimer = setTimeout(function () {
      loadHealth();
      loadConfig();
    }, 400);
  }
  window.addEventListener("dh-step8-visible", scheduleRefresh);
  window.loadStep9Data = function () {
    loadHealth();
    loadConfig();
  };
  var originalNavigate = window.navigateToStep;
  window.navigateToStep = function (step) {
    if (Number(step) === 9) {
      scheduleRefresh();
    }
    return originalNavigate ? originalNavigate.apply(this, arguments) : undefined;
  };
  // 可选步骤完成态同步：启用/关闭数字人时刷新左侧步骤条
  var _dhSyncStepper = function () {
    if (typeof window.refreshCurrentProjectStatus === "function") {
      try { window.refreshCurrentProjectStatus(9); } catch (e) {}
    }
  };
  window.__dhMarkEnabled = function (enabled) {
    window.__dhEnabled = !!enabled;
    _dhSyncStepper();
  };
  window.__dhMarkEnabled(window.__dhEnabled === true);
})();
