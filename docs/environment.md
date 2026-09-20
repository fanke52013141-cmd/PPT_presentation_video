# Environment configuration

The application is local-first. The values in `.env.example` are sufficient for
normal local use. Do not put real credentials in `.env.example`, source files,
or shell command arguments.

## Network access

| Variable | Default | Use |
| --- | --- | --- |
| `PPT_STUDIO_HOST` | `127.0.0.1` | Bind address. A non-loopback host requires `PPT_STUDIO_ACCESS_TOKEN`. |
| `PPT_STUDIO_PORT` | `8000` | HTTP port. |
| `PPT_STUDIO_ACCESS_TOKEN` | unset | Required for non-loopback exposure. |
| `PPT_STUDIO_ALLOWED_ORIGINS` | unset | Additional trusted browser origins for proxy or LAN deployments. |
| `PPT_STUDIO_ALLOWED_HOSTS` | unset | Additional trusted Host headers. |
| `PPT_STUDIO_SECURE_COOKIE` | false | Enable only behind HTTPS. |
| `PPT_STUDIO_AUTH_COOKIE_MAX_AGE` | `43200` | Authentication-cookie lifetime in seconds. |
| `PPT_STUDIO_AUTH_EXEMPT_PATHS` | unset | Comma-separated exceptional paths; treat as a security-sensitive setting. |
| `PPT_STUDIO_ALLOW_INSECURE_NETWORK` | false | Development escape hatch. Do not enable in a shared network. |

## Storage and media tools

| Variable | Default | Use |
| --- | --- | --- |
| `PPT_STUDIO_RUNS_DIR` | repository `runs/` | Project runtime-data root. |
| `PPT_STUDIO_DB_PATH` | repository data database | SQLite path. Keep it on a local, writable volume. |
| `PPT_STUDIO_JOURNAL_MODE` | application default | SQLite journal override for diagnosed deployment needs only. |
| `PPT_STUDIO_FFMPEG_DIR` | auto-detected by launchers | Directory containing `ffmpeg` and `ffprobe`. |
| `PPT_STUDIO_ASSETS_DIR` | `D:\PPT_Studio_Assets` in Windows launchers | Optional local asset root. |
| `PPT_STUDIO_RENDER_ACCELERATION` | `auto` | Encoder selection. Use an explicit mode only after validating output on that machine. |
| `PPT_STUDIO_REVEAL_BUILD_TIMEOUT_SEC` | application default | Bound for Reveal asset construction. |

## Providers and integrations

| Variable group | Use |
| --- | --- |
| `PPT_STUDIO_TTS_API_KEY`, `PPT_STUDIO_TTS_SECRET_KEY`, `PPT_COMFYUI_URL` | Provider credentials and local ComfyUI endpoint. Prefer the settings UI or the OS secret store where available. |
| `PPT_AGENT_API_KEY`, `PPT_AGENT_API_URL`, `PPT_APP_TOKEN`, `PPT_MCP_CONTRACT_CHECK`, `PPT_AGENT_TRUST_PROXY_HEADERS` | Agent/CLI/MCP integration. `PPT_APP_TOKEN` is a legacy fallback; prefer `PPT_AGENT_API_KEY`. Enable proxy-header trust only behind a known proxy. |
| `PPT_DIGITAL_HUMAN_*` | Optional digital-human service, assets, backend, workflow, Python interpreter, and port settings. This feature is optional and must not block video export. |

## Limits

| Variable | Use |
| --- | --- |
| `PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES`, `PPT_STUDIO_MAX_IMAGE_PIXELS` | Image-upload size and decode-pixel limits. |
| `PPT_STUDIO_MAX_IP_IMAGE_BYTES` | IP-character image upload limit. |
| `PPT_STUDIO_MAX_CONFIG_IMPORT_BYTES` | Configuration import size limit. |
| `PPT_DIGITAL_HUMAN_MAX_AVATAR_BYTES`, `PPT_MAX_AVATAR_UPLOAD_BYTES`, `PPT_MAX_UPLOAD_VIDEO_BYTES`, `PPT_MAX_WORKFLOW_BYTES`, `PPT_MAX_WORKFLOW_NODES` | Digital-human upload and workflow limits. |

Variables beginning with `PPT_STUDIO_MASKED_VALUE__` and
`PPT_STUDIO_REDACTED__` are internal sentinels, not operator configuration.
Test-only overrides such as `PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR` must
never be used in production.
