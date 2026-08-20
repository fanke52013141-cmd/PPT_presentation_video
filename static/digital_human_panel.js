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
      mode: "upload",
      shape: "circle",
      avatar_id: "",
      circle: { cx: 0.8, cy: 0.2, r: 0.25 },
      video: { ox: 0.5, oy: 0.5, zoom: 1.0 },
      slides: {},
    },
    avatars: [],
    audioReady: {},
    polling: {},
    uploadVideoExists: false,
    videoSize: null, // {w,h} 预览视频原始尺寸
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
      if (res && res.audioReady) dhState.audioReady = res.audioReady;
      if (res && res.slides) {
        dhState.config.slides = res.slides;
        renderSlideStatus();
      }
      dhState.uploadVideoExists = !!(res && res.upload_video_exists);
      applyConfigToUI();
      loadPreview();
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
    var avatarSel = document.getElementById("dh-avatar-select");
    var uploadStatus = document.getElementById("dh-upload-status");
    if (enabledEl) enabledEl.checked = !!dhState.config.enabled;
    if (body) body.style.display = dhState.config.enabled ? "" : "none";
    if (avatarSel && dhState.config.avatar_id) avatarSel.value = dhState.config.avatar_id;
    if (uploadStatus) {
      uploadStatus.textContent = dhState.uploadVideoExists ? "已上传" : "未上传";
      uploadStatus.className = "dh-upload-status " + (dhState.uploadVideoExists ? "dh-done" : "dh-failed");
    }
    var zoomEl = document.getElementById("dh-video-zoom");
    if (zoomEl) zoomEl.value = String(dhState.config.video && dhState.config.video.zoom || 1);
    // 形状切换高亮
    document.querySelectorAll("[data-dh-shape]").forEach(function (btn) {
      var active = btn.getAttribute("data-dh-shape") === (dhState.config.shape || "circle");
      btn.classList.toggle("dh-shape-active", active);
    });
    applyCircleToPreview();
  }

  async function saveConfig() {
    var pid = projectId();
    if (!pid) return;
    var enabledEl = document.getElementById("dh-enabled");
    var avatarSel = document.getElementById("dh-avatar-select");
    var syncEl = document.getElementById("dh-sync-mode");
    dhState.config.enabled = enabledEl ? enabledEl.checked : false;
    dhState.config.avatar_id = avatarSel ? avatarSel.value : "";
    dhState.config.sync_mode = syncEl ? syncEl.value : "accurate";
    try {
      await API.put(base() + "/config", {
        enabled: dhState.config.enabled,
        mode: dhState.config.mode || "upload",
        shape: dhState.config.shape || "circle",
        avatar_id: dhState.config.avatar_id,
        sync_mode: dhState.config.sync_mode,
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
    try {
      var res = await API.get(base() + "/health");
      if (res && res.model_ready) {
        el.textContent = "模型就绪";
        el.className = "dh-service-status dh-ok";
      } else {
        el.textContent = res && res.mock_mode ? "Mock 模式" : "模型未部署";
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
        captureVideoFirstFrame();
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

    var cxEl = document.getElementById("dh-cx");
    var cyEl = document.getElementById("dh-cy");
    var rEl = document.getElementById("dh-r");
    var oxEl = document.getElementById("dh-ox");
    var oyEl = document.getElementById("dh-oy");
    if (cxEl) cxEl.textContent = circle.cx.toFixed(2);
    if (cyEl) cyEl.textContent = circle.cy.toFixed(2);
    if (rEl) rEl.textContent = circle.r.toFixed(2);
    if (oxEl) oxEl.textContent = videoCfg.ox.toFixed(2);
    if (oyEl) oyEl.textContent = videoCfg.oy.toFixed(2);
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
    if (dhState.uploadVideoExists) {
      src = base() + "/upload/video?t=" + Date.now();
    } else {
      // 回退：优先用第一页已生成的数字人视频，否则用形象视频
      var slides = dhState.config.slides || {};
      var firstDone = Object.keys(slides).find(function (sid) {
        return slides[sid] && slides[sid].video_exists;
      });
      if (firstDone) {
        src = base() + "/slides/" + encodeURIComponent(firstDone) + "/video?t=" + Date.now();
      } else if (dhState.config.avatar_id) {
        src = base() + "/avatars/" + encodeURIComponent(dhState.config.avatar_id) + "/video?t=" + Date.now();
      }
    }
    if (src) {
      video.src = src;
      video.play().catch(function () {});
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

  // ---------------- 位置预设 / 重置 ----------------

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

  // ---------------- 生成（LatentSync，保留） ----------------

  function audioReadySlides() {
    return Object.keys(dhState.audioReady || {}).filter(function (sid) {
      return dhState.audioReady[sid];
    });
  }

  async function generateSlide(slideId) {
    var pid = projectId();
    if (!pid) return;
    if (!dhState.config.avatar_id) {
      showToast("请先上传并选择讲解形象");
      return;
    }
    try {
      var res = await API.post(base() + "/generate/" + encodeURIComponent(slideId), {
        avatar_id: dhState.config.avatar_id,
        sync_mode: dhState.config.sync_mode || "accurate",
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
    renderSlideStatus();
  }

  async function pollJob(slideId, jobId) {
    if (dhState.polling[jobId]) return;
    dhState.polling[jobId] = true;
    try {
      for (var i = 0; i < 600; i++) {
        await sleep(2000);
        var res = await API.get(base() + "/jobs/" + encodeURIComponent(jobId));
        var job = res && res.job ? res.job : res;
        var status = job && job.status;
        if (status === "done") {
          markSlideStatus(slideId, "done");
          loadPreview();
          showToast("页面 " + slideId + " 数字人已生成");
          break;
        } else if (status === "failed") {
          markSlideStatus(slideId, "failed");
          showToast("页面 " + slideId + " 生成失败：" + ((job && job.error) || "未知错误"));
          break;
        } else if (status === "unavailable") {
          markSlideStatus(slideId, "failed");
          showToast("模型未部署，无法生成");
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
    var ids = audioReadySlides();
    if (!ids.length) {
      showToast("暂无可生成的页面（需先生成旁白音频）");
      return;
    }
    if (!dhState.config.avatar_id) {
      showToast("请先上传并选择讲解形象");
      return;
    }
    showToast("开始生成 " + ids.length + " 页数字人...");
    for (var i = 0; i < ids.length; i++) {
      await generateSlide(ids[i]);
    }
  }

  function renderSlideStatus() {
    var container = document.getElementById("dh-slide-status");
    if (!container) return;
    var slides = dhState.config.slides || {};
    var keys = Object.keys(slides);
    if (!keys.length) {
      container.innerHTML = '<span class="dh-slide-status-note">尚未生成任何页面</span>';
      return;
    }
    var labels = { queued: "排队中", processing: "生成中", done: "完成", failed: "失败" };
    container.innerHTML = keys.map(function (sid) {
      var item = slides[sid] || {};
      var st = item.status || "queued";
      var cls = st === "done" ? "dh-done" : st === "failed" ? "dh-failed" : "dh-busy";
      return '<span class="dh-slide-chip ' + cls + '">' + escHtml(sid) + " " + (labels[st] || st) + "</span>";
    }).join("");
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // ---------------- 初始化 ----------------

  function init() {
    var panel = document.getElementById("digital-human-panel");
    if (!panel) return;

    var enabledEl = document.getElementById("dh-enabled");
    var avatarSel = document.getElementById("dh-avatar-select");
    var avatarFile = document.getElementById("dh-avatar-file");
    var uploadVideoFile = document.getElementById("dh-upload-video-file");
    var zoomEl = document.getElementById("dh-video-zoom");
    var btnGenAll = document.getElementById("dh-btn-generate-all");
    var btnSave = document.getElementById("dh-btn-save");
    var btnReset = document.getElementById("dh-circle-reset");

    if (enabledEl) {
      enabledEl.addEventListener("change", function () {
        var body = document.getElementById("dh-panel-body");
        if (body) body.style.display = enabledEl.checked ? "" : "none";
        saveConfig();
      });
    }
    if (avatarSel) {
      avatarSel.addEventListener("change", function () {
        dhState.config.avatar_id = avatarSel.value;
        saveConfig();
        loadPreview();
      });
    }
    if (avatarFile) {
      avatarFile.addEventListener("change", function () {
        uploadAvatar(avatarFile.files && avatarFile.files[0]);
        avatarFile.value = "";
      });
    }
    if (uploadVideoFile) {
      uploadVideoFile.addEventListener("change", function () {
        uploadDigiVideo(uploadVideoFile.files && uploadVideoFile.files[0]);
        uploadVideoFile.value = "";
      });
    }
    if (zoomEl) {
      zoomEl.addEventListener("input", function () {
        if (!dhState.config.video) dhState.config.video = { ox: 0.5, oy: 0.5, zoom: 1.0 };
        dhState.config.video.zoom = Number(zoomEl.value) || 1;
        applyCircleToPreview();
      });
      zoomEl.addEventListener("change", function () {
        saveConfig();
      });
    }
    if (btnGenAll) btnGenAll.addEventListener("click", generateAll);
    if (btnSave) btnSave.addEventListener("click", saveConfig);
    if (btnReset) btnReset.addEventListener("click", resetCircle);

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

    document.querySelectorAll("[data-dh-pos]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setPositionPreset(btn.getAttribute("data-dh-pos"));
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
    loadHealth();
    loadConfig();
    loadAvatars();
  }

  // 保留 LatentSync 生成模式的形象上传逻辑
  async function loadAvatars() {
    var sel = document.getElementById("dh-avatar-select");
    if (!sel) return;
    try {
      var res = await API.get(base() + "/avatars");
      dhState.avatars = (res && res.avatars) || [];
      sel.innerHTML = '<option value="">选择讲解形象（参考视频）</option>' +
        dhState.avatars.map(function (a) {
          return '<option value="' + escHtml(a.avatar_id) + '">' + escHtml(a.filename) + "</option>";
        }).join("");
      if (dhState.config.avatar_id) sel.value = dhState.config.avatar_id;
    } catch (e) {
      console.error("[DH] loadAvatars failed:", e);
    }
  }

  async function uploadAvatar(file) {
    if (!file) return;
    var fd = new FormData();
    fd.append("file", file);
    fd.append("name", file.name);
    try {
      var res = await API.post(base() + "/avatars", fd);
      if (res && res.avatar_id) {
        showToast("参考视频已上传");
        dhState.config.avatar_id = res.avatar_id;
        await loadAvatars();
        await saveConfig();
      }
    } catch (e) {
      console.error("[DH] uploadAvatar failed:", e);
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
    loadAvatars();
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
