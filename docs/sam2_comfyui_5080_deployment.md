# SAM2 智能分割 · RTX 5080 机器部署说明

本说明面向"两台机器协同"的部署形态：开发机（无 GPU）运行 PPT_presentation_video
主应用，RTX 5080 机器运行 ComfyUI 并提供 SAM2 分割能力。主应用通过局域网 HTTP
调用 ComfyUI；调用失败或服务不可达时自动回退到原有确定性白底方案，不阻断业务。

代码侧的适配已全部写好，本文件只需要在 5080 那台机器上按步骤操作。

---

## 一、整体分工与调用关系

- 5080 机器：安装并启动 ComfyUI，安装 kijai 的 SAM2 节点，准备 SAM2.1 权重，
  监听局域网地址，端口默认 8188。
- 开发机：在 AI Mask 设置里把 ComfyUI 地址指向 5080 机器的局域网 IP。运行 AI Mask
  时，主应用先探测该地址，节点齐全则走 SAM2 智能分割，否则静默回退。
- 数据契约不变：SAM2 输出的黑白 mask 会被转成项目统一的 row_runs_v1 RLE，
  下游 VLM 语义匹配、assignment、reveal 组装全部复用，无需改动。

---

## 二、5080 机器侧操作

### 1. 安装支持 Blackwell 的新版 ComfyUI

RTX 5080 属于 Blackwell 架构（计算能力 sm_120），必须使用较新的 ComfyUI 与
匹配 Blackwell 的 PyTorch / CUDA 运行时，旧版本会出现无法识别 GPU、torch 报错
或算子不支持。

- 推荐直接使用 ComfyUI 官方最新的 Windows 便携版（standalone）或桌面版，
  官方新版会自带支持 Blackwell 的 PyTorch 与 CUDA 依赖，避免手动配环境。
- 若选择手动 `pip` 安装，需选用支持 Blackwell 的 PyTorch（CUDA 12.8 及以上方向），
  具体版本号以 PyTorch 官方与 ComfyUI 文档当前给出的 Blackwell 安装指引为准，
  这里不写死版本号以免过时。
- 安装后先单独启动一次 ComfyUI，确认能正常打开 `http://127.0.0.1:8188`，
  且控制台没有 CUDA / torch 报错。

### 2. 安装 kijai 的 SAM2 节点

节点包名称：`ComfyUI-segment-anything-2`（作者 kijai）。

- 方式一（推荐）：使用 ComfyUI Manager，搜索 "ComfyUI-segment-anything-2"
  安装后重启 ComfyUI。
- 方式二（手动）：在 `ComfyUI/custom_nodes/` 目录下执行
  `git clone https://github.com/kijai/ComfyUI-segment-anything-2.git`，
  然后重启 ComfyUI。

安装后确认以下节点可用（开发机探测时会校验这些 class_type）：
`DownloadAndLoadSAM2Model`、`Sam2Segmentation`。
另外 `Mask To Image`、`SaveImage`、`LoadImage` 是 ComfyUI 自带核心节点，无需额外安装。

### 3. 准备 SAM2.1 权重

默认档位为 large，对应权重文件 `sam2.1_hiera_large.safetensors`。

- 方式一（自动，推荐）：无需手动下载。在 ComfyUI 里首次运行使用该模型的工作流时，
  `DownloadAndLoadSAM2Model` 节点会自动从 HuggingFace（Kijai/sam2-safetensors）
  下载，并存入 `ComfyUI/models/sam2/`，之后复用。
- 方式二（手动）：若 5080 机器访问 HuggingFace 不畅，可在能联网的环境下载对应
  safetensors 文件，手动放入 `ComfyUI/models/sam2/` 目录。
- 各档位对应文件名（与开发机设置 `sam2_tier` 对应）：
  - tiny：`sam2.1_hiera_tiny.safetensors`
  - small：`sam2.1_hiera_small.safetensors`
  - base_plus：`sam2.1_hiera_base_plus.safetensors`
  - large：`sam2.1_hiera_large.safetensors`
- 5080 16GB 显存对四个档位均无压力，large 精度最高，建议保持默认 large；
  若追求更快速度可在设置里降到 small 或 base_plus。

### 4. 让 ComfyUI 监听局域网地址（关键）

ComfyUI 默认只监听 `127.0.0.1`，开发机无法跨机器访问。启动时需要加监听参数：

- 命令行启动：
  `python main.py --listen 0.0.0.0 --port 8188`
- Windows 便携版：可编辑启动用的 bat（如 `run_nvidia_gpu.bat`），在启动命令后
  追加 `--listen 0.0.0.0`；桌面版可在启动参数设置中添加。
- `--listen 0.0.0.0` 表示监听所有网卡，同一局域网内的设备才能访问。

### 5. 放行防火墙端口

Windows Defender 防火墙默认可能拦截 8188 的入站连接。首次启动监听时若弹出
网络访问提示，选择"允许"；若没有弹窗，可在"Windows  Defender 防火墙 → 高级设置 →
入站规则"中为 ComfyUI 或 8188 端口新建一条允许规则（仅专用网络即可）。

### 6. 查询 5080 机器的局域网 IP

在 5080 机器上打开 PowerShell 执行 `ipconfig`，找到当前网卡的"IPv4 地址"，
形如 `192.168.x.x`（例如 `192.168.1.20`）。记下这个地址，开发机配置要用。

---

## 三、开发机侧配置

在应用的 AI Mask 设置中填写：

- `comfyui_base_url`：填 5080 机器地址，例如 `http://192.168.1.20:8188`。
  注意这里不能用 `127.0.0.1`，那指的是开发机自己。
- `segmentation_device_mode`：保持 `auto`。自动探测到可用 ComfyUI 就走 SAM2，
  探测不到就回退确定性方案。
  - 设为 `cpu`：强制使用原有确定性白底方案，不调用 ComfyUI。
  - 设为 `cuda`：要求 GPU 后端，探测不到 GPU 时回退确定性方案。
- `sam2_tier`：保持 `large`，需与 5080 机器实际准备的权重一致。
- `sam2_workflow_path`：留空，使用项目内置模板
  `config/sam2_segmentation_api.json`。若后续更换节点包或自定义工作流，
  可在此指定外部模板路径，无需改代码。

支持在 `comfyui_base_url` 里用英文逗号分隔多个候选地址，主应用会按顺序探测，
取第一个可用的。

---

## 四、联通验证

1. 在开发机浏览器直接访问 `http://192.168.1.20:8188/object_info`，
   能返回 JSON 即说明网络与端口可达。
2. 在项目里运行一次 AI Mask 自动标注。若后端可用，输出元素会带
   `segmentation_engine = "sam2"` 标识；若不可用则自动回退，结果仍正常产出。
3. 手动智能选区验证：在 Step 5 语块卡片上点"智能选区"按钮，进入点选模式，
   在画面上点击放置正点（Alt/右键放负点），点"生成选区"，确认蒙版贴合对象。
4. 若 5080 机器关机或 ComfyUI 未启动，主应用探测失败后会静默回退，
   不影响正常使用。

---

## 五、安全与网络注意事项

- `--listen 0.0.0.0` 会让同一局域网内的设备都能访问该 ComfyUI，请仅在可信的
  家庭/办公内网使用，不要把 8188 端口映射到公网。
- 两台机器需在同一局域网且能互通；若经过路由器 AP 隔离或 VLAN 隔离，
  需在网络设置中关闭相关隔离。
- 所有主应用侧的 ComfyUI 调用都关闭了系统代理（trust_env=False），
  避免本机代理设置导致局域网地址被劫持。

---

## 六、常见问题排查

- 开发机连不上：先确认 5080 机器 ComfyUI 已用 `--listen 0.0.0.0` 启动、
  防火墙已放行、两台机器互相 ping 得通、IP 地址正确。
- 提示缺少节点：节点未安装或安装后未重启 ComfyUI，按第二节第 2 步处理。
- 首次分割很慢：通常是权重正在自动下载，等待下载完成后会变快；
  也可观察 ComfyUI 控制台下载进度。
- 5080 报 CUDA / torch 错误：多为 ComfyUI 或 PyTorch 版本过旧不支持 Blackwell，
  升级到官方最新版与匹配的 Blackwell 运行时。
- 智能选区结果不贴合：在对象内部补一个正点、在误选区域放负点后重新生成；
  仍不理想可退回画笔/橡皮手动修正。
