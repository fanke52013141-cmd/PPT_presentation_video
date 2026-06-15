import os
import io
import sys
import uuid
import json
import shutil
import logging
import subprocess
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image
import httpx
from openai import OpenAI

def get_openai_client(api_key: str, base_url: str = None, timeout: float = 120.0, max_retries: int = 1) -> OpenAI:
    # 强制不使用环境变量中的代理，防止某些局域网代理的 SSL 拦截规则冲突
    # 并强制定义 User-Agent 为 Chrome 浏览器以绕过 Cloudflare WAF/JA3 爬虫过滤指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    http_client = httpx.Client(
        limits=limits,
        trust_env=False,
        headers=headers,
        timeout=timeout
    )
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=timeout,
        max_retries=max_retries,
    )

from database import init_db, get_db, Project, Setting
from config_store import get_all_settings, update_settings, get_setting

# 初始化日志与数据库
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PPTStudio")
init_db()

app = FastAPI(title="PPT Visualization Studio", description="本地手绘线稿风 PPT 视频生成系统")

# 解决跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "runs"))
os.makedirs(RUNS_DIR, exist_ok=True)

STEP1_LLM_TIMEOUT_SEC = 60.0
STEP2_LLM_TIMEOUT_SEC = 120.0
STEP7_TTS_TIMEOUT_SEC = 180
STEP7_BIND_TIMEOUT_SEC = 60

def _redact_log_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("api_key", "apikey", "authorization", "token", "secret")):
        return "***REDACTED***" if value else value
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + f"\n... [truncated {len(value) - 4000} chars]"
    return value

def write_project_log(project: Project, event: str, **fields: Any) -> None:
    try:
        log_dir = os.path.join(project.run_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "project_id": project.id,
            "event": event,
        }
        record.update({key: _redact_log_value(key, value) for key, value in fields.items()})
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(os.path.join(log_dir, "pipeline.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info("project=%s event=%s %s", project.id, event, line)
    except Exception as exc:
        logger.warning("Failed to write project log for %s: %s", getattr(project, "id", "<unknown>"), exc)

def should_retry_without_response_format(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "response_format",
            "json_object",
            "unsupported",
            "unrecognized",
            "invalid parameter",
            "not support",
            "400",
        )
    )

# Pydantic 响应模型
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

class StepUpdate(BaseModel):
    step_data: Dict[str, Any]

class TestLlmPayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str

class TestImagePayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str

class TestTtsPayload(BaseModel):
    endpoint: str
    api_key: str
    model: str
    voice_id: str

# 图片后处理：将任意尺寸等比例缩放，并居中贴在 #FFFDF7 暖白背景的 1920x1080 画布上
def process_and_save_image(image_bytes: bytes, save_path: str):
    bg_color = (255, 253, 247)  # #FFFDF7
    target_width, target_height = 1920, 1080
    
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
        
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height
    
    if img_ratio > target_ratio:
        new_width = target_width
        new_height = int(target_width / img_ratio)
    else:
        new_height = target_height
        new_width = int(target_height * img_ratio)
        
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 居中贴合到 1920x1080 的温暖极简底图上
    final_img = Image.new("RGB", (target_width, target_height), bg_color)
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    final_img.paste(resized_img, (paste_x, paste_y))
    
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    final_img.save(save_path, "PNG")
    logger.info(f"Image processed and saved to: {save_path}")

def clean_json_markdown(text: str) -> str:
    text = text.strip()
    
    # 移除 ```json 和 ``` 包裹
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        else:
            text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
            
    # 特殊容错：有些大模型会在前后附加解释文本，我们尝试提取第一个 { 或 [ 到最后一个 } 或 ]
    first_brace = text.find("{")
    first_bracket = text.find("[")
    
    start_idx = -1
    end_idx = -1
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_idx = text.rfind("}")
    elif first_bracket != -1:
        start_idx = first_bracket
        end_idx = text.rfind("]")
        
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]
        
    return text

# ==================== 项目管理接口 ====================

@app.post("/api/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project_id = str(uuid.uuid4())[:8] + "_" + datetime.now().strftime("%H%M%S")
    run_dir = os.path.join(RUNS_DIR, project_id)
    
    # 初始化文件夹结构
    os.makedirs(os.path.join(run_dir, "inputs"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "planning"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "slides"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "review"), exist_ok=True)
    
    # 初始化默认步骤状态字典：1到8步均为 pending
    initial_step_status = {str(i): "pending" for i in range(1, 9)}
    
    db_project = Project(
        id=project_id,
        name=payload.name,
        description=payload.description,
        current_step=1,
        status="active",
        run_dir=run_dir
    )
    db_project.set_step_status(initial_step_status)
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    
    return {
        "success": True, 
        "project": {
            "id": db_project.id,
            "name": db_project.name,
            "description": db_project.description,
            "current_step": db_project.current_step,
            "step_status": db_project.get_step_status()
        }
    }

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "current_step": p.current_step,
        "status": p.status,
        "step_status": p.get_step_status(),
        "created_at": p.created_at.isoformat()
    } for p in projects]

@app.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "current_step": project.current_step,
        "status": project.status,
        "step_status": project.get_step_status(),
        "run_dir": project.run_dir
    }

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 物理删除 runs 文件夹
    if os.path.exists(project.run_dir):
        try:
            shutil.rmtree(project.run_dir)
        except Exception as e:
            logger.error(f"Failed to delete directory {project.run_dir}: {e}")
            
    db.delete(project)
    db.commit()
    return {"success": True, "message": "项目删除成功"}

# ==================== 设置管理接口 ====================

@app.get("/api/settings")
def get_settings():
    return get_all_settings()

@app.put("/api/settings")
def update_system_settings(payload: SettingsUpdate):
    update_settings(payload.settings)
    return {"success": True, "message": "设置更新成功"}

@app.post("/api/settings/test-llm")
def test_llm_connection(payload: TestLlmPayload):
    try:
        client = get_openai_client(api_key=payload.api_key, base_url=payload.base_url)
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            timeout=10
        )
        content = response.choices[0].message.content
        return {"success": True, "message": f"连接成功！模型响应: '{content.strip()}'"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

@app.post("/api/settings/test-image")
def test_image_connection(payload: TestImagePayload):
    try:
        client = get_openai_client(api_key=payload.api_key, base_url=payload.base_url)
        try:
            response = client.images.generate(
                model=payload.model,
                prompt="a single dot",
                size="1024x1024",
                n=1,
                timeout=15
            )
        except Exception:
            response = client.images.generate(
                model=payload.model,
                prompt="a single dot",
                n=1,
                timeout=15
            )
        if response.data:
            return {"success": True, "message": "连接成功！生图接口响应正常。"}
        return {"success": False, "message": "未返回有效图片数据。"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

@app.post("/api/settings/test-tts")
def test_tts_connection(payload: TestTtsPayload):
    try:
        url = payload.endpoint
        headers = {
            "Authorization": f"Bearer {payload.api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": payload.model,
            "text": "测试",
            "voice_setting": {
                "voice_id": payload.voice_id,
                "speed": 1.0,
                "volume": 1.0,
                "pitch": 0
            },
            "audio_setting": {
                "sample_rate": 16000,
                "bitrate": 128000,
                "format": "mp3"
            }
        }
        res = httpx.post(url, headers=headers, json=body, timeout=15)
        if res.status_code != 200:
            return {"success": False, "message": f"接口请求失败: HTTP {res.status_code}, 内容: {res.text[:100]}"}
        
        content_type = res.headers.get("content-type", "")
        if "audio" in content_type or len(res.content) > 100:
            if b"{" in res.content[:50]:
                try:
                    err_json = res.json()
                    status_msg = err_json.get("base_resp", {}).get("status_msg", "")
                    if status_msg and status_msg != "success":
                        return {"success": False, "message": f"连接失败: {status_msg}"}
                except Exception:
                    pass
            return {"success": True, "message": "连接成功！TTS 合成接口可以正常响应。"}
        return {"success": False, "message": f"未返回音频数据。响应内容: {res.text[:100]}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

# ==================== 流水线状态管理 ====================

# 回退某一步后，后续步骤状态被标记为 pending_reconfirmation
def handle_step_navigation(project: Project, target_step: int, db: Session):
    current_status = project.get_step_status()
    
    # 规则：对于大于 target_step 且原本状态不为 "pending" 的步骤，将其标记为 "pending_reconfirmation"
    for s_idx in range(target_step + 1, 9):
        s_str = str(s_idx)
        if current_status.get(s_str) in ["completed", "in_progress", "pending_reconfirmation"]:
            current_status[s_str] = "pending_reconfirmation"

    # If a later step completes, any earlier "needs reconfirmation" step has
    # effectively been reconfirmed by that later successful run.
    for s_idx in range(1, target_step):
        s_str = str(s_idx)
        if current_status.get(s_str) == "pending_reconfirmation":
            current_status[s_str] = "completed"

    current_status[str(target_step)] = "completed"
    project.current_step = max(project.current_step or target_step, target_step)
    project.set_step_status(current_status)
    db.commit()

@app.post("/api/projects/{project_id}/navigate")
def navigate_project(project_id: str, target_step: int = Form(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    handle_step_navigation(project, target_step, db)
    return {
        "success": True,
        "project": {
            "id": project.id,
            "current_step": project.current_step,
            "step_status": project.get_step_status()
        }
    }

# ==================== 步骤 1: 导入文章 ====================

@app.post("/api/projects/{project_id}/steps/1/import")
def import_article(project_id: str, content: Optional[str] = Form(None), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="请输入有效的文章内容")

    article_path = os.path.join(project.run_dir, "inputs", "article.md")
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # 调用 LLM 做文章提炼
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")

    write_project_log(
        project,
        "step1_import_start",
        article_chars=len(content),
        model=llm_model,
        base_url=llm_base_url,
        timeout_sec=STEP1_LLM_TIMEOUT_SEC,
    )
    client = get_openai_client(
        api_key=llm_api_key,
        base_url=llm_base_url,
        timeout=STEP1_LLM_TIMEOUT_SEC,
        max_retries=0,
    )
    system_prompt = "你是一个专业的内容提炼助手。请阅读用户输入的 Markdown 文章，提炼出它的核心标题以及一份易于视频分镜表达的摘要提纲（150字以内）。请直接返回 JSON 格式结果，格式为: {\"title\": \"标题\", \"summary\": \"提炼好的摘要提纲\", \"content\": \"原文\"}"
    
    try:
        started_at = time.monotonic()
        response = client.chat.completions.create(
            model=llm_model,
            temperature=llm_temp,
            response_format={"type": "json_object"},
            timeout=STEP1_LLM_TIMEOUT_SEC,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )
        elapsed = round(time.monotonic() - started_at, 3)
        content_str = response.choices[0].message.content.strip()
        write_project_log(
            project,
            "step1_llm_success",
            elapsed_sec=elapsed,
            response_chars=len(content_str),
        )
        cleaned_content = clean_json_markdown(content_str)
        brief = json.loads(cleaned_content)
        brief["content"] = content
    except Exception as e:
        write_project_log(project, "step1_llm_error", error_type=type(e).__name__, error=str(e))
        logger.error(f"LLM ingest article error: {e}")
        raise HTTPException(status_code=500, detail=f"文章提炼失败: {str(e)}")
            
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
        
    handle_step_navigation(project, 1, db)
    write_project_log(project, "step1_import_completed", brief_path=brief_path)
    return {"success": True, "brief": brief}

@app.get("/api/projects/{project_id}/steps/1/result")
def get_step1_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        return {"success": False, "message": "尚未导入文章"}
        
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)
    return {"success": True, "brief": brief}

@app.put("/api/projects/{project_id}/steps/1/result")
def update_step1_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    # 同步回写 article.md
    if "content" in payload:
        article_path = os.path.join(project.run_dir, "inputs", "article.md")
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(payload["content"])
            
    return {"success": True, "brief": payload}

# ==================== 步骤 2: 智能分镜规划 ====================

@app.post("/api/projects/{project_id}/steps/2/execute")
def execute_step2(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        raise HTTPException(status_code=400, detail="请先导入文章再生成分镜")
        
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    trace_id = uuid.uuid4().hex[:8]
    article_path = os.path.join(project.run_dir, "inputs", "article.md")
    write_project_log(
        project,
        "step2_execute_start",
        trace_id=trace_id,
        mode="local_scaffold",
        brief_title=brief.get("title"),
        summary_chars=len(str(brief.get("summary", ""))),
        content_chars=len(str(brief.get("content", ""))),
    )

    try:
        if not os.path.exists(article_path):
            content = str(brief.get("content", "")).strip()
            if not content:
                raise RuntimeError("article.md 不存在，且 article_brief.json 中没有 content 字段，无法生成分镜骨架")
            os.makedirs(os.path.dirname(article_path), exist_ok=True)
            with open(article_path, "w", encoding="utf-8") as f:
                f.write(content)
            write_project_log(project, "step2_article_restored", trace_id=trace_id, article_path=article_path)

        contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
        scaffold_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_visual_contract.py"))
        scaffold_args = [
            sys.executable,
            scaffold_script,
            "--run-dir",
            project.run_dir,
            "--topic-name",
            str(brief.get("title") or project.name),
            "--overwrite",
        ]
        started_at = time.monotonic()
        write_project_log(
            project,
            "step2_scaffold_start",
            trace_id=trace_id,
            script=scaffold_script,
            article_path=article_path,
            contract_path=contract_path,
        )
        scaffold_res = subprocess.run(
            scaffold_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        elapsed = round(time.monotonic() - started_at, 3)
        if scaffold_res.returncode != 0:
            write_project_log(
                project,
                "step2_scaffold_error",
                trace_id=trace_id,
                elapsed_sec=elapsed,
                returncode=scaffold_res.returncode,
                stdout=scaffold_res.stdout.strip(),
                stderr=scaffold_res.stderr.strip(),
            )
            raise RuntimeError(f"本地分镜骨架生成失败: {scaffold_res.stderr.strip() or scaffold_res.stdout.strip()}")

        write_project_log(
            project,
            "step2_scaffold_success",
            trace_id=trace_id,
            elapsed_sec=elapsed,
            stdout=scaffold_res.stdout.strip(),
        )

        with open(contract_path, "r", encoding="utf-8-sig") as f:
            contract = json.load(f)

        # 用第一步提炼结果覆盖 topic 元信息，避免脚本从文件名推导出不友好的标题。
        contract["version"] = "visual_contract_v1"
        contract["topic"] = {
            "topic_id": "topic_" + project_id,
            "topic_name": brief.get("title") or project.name,
            "topic_summary": brief.get("summary", ""),
        }
        with open(contract_path, "w", encoding="utf-8") as f:
            json.dump(contract, f, ensure_ascii=False, indent=2)
        write_project_log(
            project,
            "step2_contract_written",
            trace_id=trace_id,
            contract_path=contract_path,
            slide_count=len(contract.get("slides", [])) if isinstance(contract.get("slides"), list) else 0,
        )
            
        # 调用原项目的验证脚本进行 contract 校验
        validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_visual_contract.py"))
        val_res = subprocess.run([
            sys.executable, validate_script, "--contract", contract_path
        ], capture_output=True, text=True, encoding="utf-8")
        
        if val_res.returncode != 0:
            logger.warning(f"Visual contract validation warning:\n{val_res.stderr}")
            write_project_log(
                project,
                "step2_contract_validation_warning",
                trace_id=trace_id,
                returncode=val_res.returncode,
                stderr=val_res.stderr.strip(),
            )
            # 虽然校验可能报错，但如果不严重，仍然保存以方便用户在前台手动修改
        else:
            write_project_log(
                project,
                "step2_contract_validation_success",
                trace_id=trace_id,
                stdout=val_res.stdout.strip(),
            )
            
        handle_step_navigation(project, 2, db)
        write_project_log(project, "step2_execute_completed", trace_id=trace_id)
        return {"success": True, "contract": contract}
    except Exception as e:
        write_project_log(project, "step2_execute_error", trace_id=trace_id, error_type=type(e).__name__, error=str(e))
        logger.error(f"Write visual contract error: {e}")
        raise HTTPException(status_code=500, detail=f"本地分镜规划失败: {str(e)}")

@app.get("/api/projects/{project_id}/steps/2/result")
def get_step2_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        return {"success": False, "message": "尚未生成分镜规划"}
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
    return {"success": True, "contract": contract}

@app.put("/api/projects/{project_id}/steps/2/result")
def update_step2_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    return {"success": True, "contract": payload}

# ==================== 步骤 3-4: 图片生成与管理 ====================

# 辅助生成某一页 PPT 生图的 Prompt。
# 在这里，我们需要配合手绘风格的规则，将 visual_anchor 及 visible_text 与预定义的线稿艺术做融合。
def generate_prompt_for_slide(slide: Dict[str, Any], topic_name: str) -> str:
    # 提取所有视觉分组的描述
    anchors = []
    for g in slide.get("visual_groups", []):
        if g.get("role") not in ["title", "subtitle"]:
            anchors.append(f"{g.get('visible_text')}({g.get('visual_anchor')})")
            
    anchors_str = "，".join(anchors)
    main_title = slide.get("main_title", "")
    subtitle = slide.get("subtitle", "")
    subtitle_part = f"Subtitle: '{subtitle}'. " if subtitle else ""
    
    # 结合风格 tokens 与布局规则，生成契合“温暖极简手绘线稿”的 Prompt
    prompt = (
        f"A warm, minimalist, hand-drawn vector line art style presentation slide for topic '{topic_name}'. "
        f"Title: '{main_title}'. {subtitle_part}"
        f"The slide contains the following visual elements and concepts: {anchors_str}. "
        f"Uniform pure beige background #FFFDF7, clean empty bottom subtitle area. "
        f"Ink black lines (#111111), fine rough hand-drawn strokes. "
        f"Subtle single accent yellow highlight (#F9D65C) on key concepts. "
        f"Minimalist whiteboard drawing, korean line art webtoon style, cute hand sketch, no shadows, no gradients."
    )
    return prompt

@app.get("/api/projects/{project_id}/steps/3/prompts")
def get_slide_prompts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    topic_name = contract.get("topic", {}).get("topic_name", project.name)
    
    # 遍历 slide 列表，为每页拼接并自动保存生成的 prompt，供前台编辑
    slide_prompts = []
    for slide in contract.get("slides", []):
        slide_id = slide["slide_id"]
        generated_prompt = generate_prompt_for_slide(slide, topic_name)
        slide_prompts.append({
            "slide_id": slide_id,
            "title": slide["main_title"],
            "prompt": generated_prompt
        })
        
    return {"success": True, "prompts": slide_prompts}

@app.post("/api/projects/{project_id}/steps/3/generate")
def generate_slide_image(project_id: str, slide_id: str = Form(...), prompt: str = Form(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    api_key = get_setting("image_api_key")
    base_url = get_setting("image_base_url")
    model = get_setting("image_model", "gpt-image-1")
    save_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。")
        
    try:
        import base64 as b64lib
        client = get_openai_client(api_key=api_key, base_url=base_url)
        image_size = get_setting("image_size", "1024x1024")
        logger.info(f"Generating image for {slide_id} using {model}, size={image_size}, prompt: {prompt[:80]}")

        # ── 第一次尝试：带完整参数（size + quality）──
        try:
            response = client.images.generate(
                model=model,
                prompt=prompt,
                size=image_size,
                quality="standard",
                n=1
            )
        except Exception as full_params_err:
            logger.warning(
                f"Image gen with full params failed ({full_params_err}). "
                "Retrying with minimal params (no size/quality) for newapi compatibility..."
            )
            # ── 第二次尝试：仅保留 model + prompt，兼容不支持 size/quality 的中转模型 ──
            response = client.images.generate(
                model=model,
                prompt=prompt,
                n=1
            )

        # ── 兼容两种响应格式：URL 和 base64 (b64_json) ──
        img_bytes: bytes | None = None
        first_item = response.data[0]
        
        # 优先读取 b64_json（部分中转供应商直接返回 base64）
        if getattr(first_item, "b64_json", None):
            img_bytes = b64lib.b64decode(first_item.b64_json)
            logger.info(f"Image received as b64_json for {slide_id}.")
        elif getattr(first_item, "url", None):
            image_url = first_item.url
            logger.info(f"Image URL received: {image_url}. Downloading...")
            http_client = httpx.Client(timeout=60)
            img_resp = http_client.get(image_url)
            if img_resp.status_code != 200:
                raise RuntimeError(f"下载生成的图片失败: HTTP {img_resp.status_code}")
            img_bytes = img_resp.content
        else:
            raise RuntimeError("API 响应中既没有 url 也没有 b64_json，无法获取图片数据")

        process_and_save_image(img_bytes, save_path)
        logger.info(f"Image saved for {slide_id}: {save_path}")
        
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except Exception as e:
        logger.error(f"Image generation error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"生成图片失败: {str(e)}")

@app.post("/api/projects/{project_id}/steps/3/upload")
def upload_slide_image(project_id: str, slide_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    try:
        content = file.file.read()
        save_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        process_and_save_image(content, save_path)
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except Exception as e:
        logger.error(f"Upload image error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")

# 获取指定页面的图片资源接口
@app.get("/api/projects/{project_id}/slides/{slide_id}/image")
def get_slide_image_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="图片不存在")
        
    from fastapi.responses import FileResponse
    return FileResponse(img_path, media_type="image/png")

@app.get("/api/projects/{project_id}/steps/3/images")
def get_all_images(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    slides_dir = os.path.join(project.run_dir, "slides")
    results = []
    
    if os.path.exists(slides_dir):
        # 扫描 slides 目录下的子目录，按名称字母排序
        for slide_dir_name in sorted(os.listdir(slides_dir)):
            slide_path = os.path.join(slides_dir, slide_dir_name)
            if os.path.isdir(slide_path):
                img_file = os.path.join(slide_path, "visual_draft.png")
                exists = os.path.exists(img_file)
                results.append({
                    "slide_id": slide_dir_name,
                    "exists": exists,
                    "url": f"/api/projects/{project_id}/slides/{slide_dir_name}/image?t={uuid.uuid4().hex[:4]}" if exists else None
                })
    return {"success": True, "images": results}

LOCKED_MASK_REVIEW_STATUSES = {"reviewed", "approved", "manual_reviewed", "manual_adjusted", "locked"}

def refresh_unlocked_step5_boxes_from_template(project: Project, manifest_path: str) -> None:
    if not os.path.exists(manifest_path):
        return
    repo_root = os.path.abspath(os.path.dirname(__file__))
    template_script = os.path.join(repo_root, "scripts", "write_reveal_manifest_template.py")
    template_path = os.path.join(project.run_dir, "planning", "reveal_manifest.template_refresh.json")
    os.makedirs(os.path.dirname(template_path), exist_ok=True)
    res = subprocess.run([
        sys.executable,
        template_script,
        "--run-dir",
        project.run_dir,
        "--out",
        template_path,
        "--overwrite",
    ], capture_output=True, text=True, encoding="utf-8", timeout=90)
    if res.returncode != 0:
        write_project_log(
            project,
            "step5_template_refresh_error",
            returncode=res.returncode,
            stdout=res.stdout.strip(),
            stderr=res.stderr.strip(),
        )
        return

    with open(manifest_path, "r", encoding="utf-8-sig") as f:
        current = json.load(f)
    with open(template_path, "r", encoding="utf-8-sig") as f:
        template = json.load(f)

    current_by_slide = {
        str(slide.get("slide_id")): slide
        for slide in current.get("slides", [])
        if isinstance(slide, dict)
    }
    merged_slides = []
    for template_slide in template.get("slides", []):
        if not isinstance(template_slide, dict):
            continue
        slide_id = str(template_slide.get("slide_id", ""))
        current_slide = current_by_slide.get(slide_id, {})
        current_groups = {
            str(group.get("id")): group
            for group in current_slide.get("groups", [])
            if isinstance(group, dict)
        }
        template_group_ids = set()
        merged_groups = []
        for template_group in template_slide.get("groups", []):
            if not isinstance(template_group, dict):
                continue
            group_id = str(template_group.get("id", ""))
            template_group_ids.add(group_id)
            current_group = current_groups.get(group_id)
            if current_group and str(current_group.get("review_status", "")).strip() in LOCKED_MASK_REVIEW_STATUSES:
                merged_groups.append(current_group)
                continue
            merged_group = dict(template_group)
            if current_group:
                # Keep the user's current reveal style and narration binding, but reset the search box.
                for key in ("reveal", "narration_beat_id", "linked_segment_id", "link_to_narration"):
                    if key in current_group:
                        merged_group[key] = current_group[key]
                if current_group.get("visible_text"):
                    merged_group["visible_text"] = current_group["visible_text"]
                if current_group.get("visual_anchor"):
                    merged_group["visual_anchor"] = current_group["visual_anchor"]
            merged_groups.append(merged_group)
        for group_id, current_group in current_groups.items():
            if group_id not in template_group_ids:
                merged_groups.append(current_group)
        merged_slide = {**template_slide, **{key: value for key, value in current_slide.items() if key not in {"groups", "reveal_boxes"}}}
        merged_slide["groups"] = merged_groups
        merged_slides.append(merged_slide)

    current["slides"] = merged_slides
    current.pop("reveal_boxes", None)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    write_project_log(project, "step5_template_refresh_success", stdout=res.stdout.strip())

def run_step5_local_masking(project: Project, manifest_path: str, source: str) -> Dict[str, Any]:
    repo_root = os.path.abspath(os.path.dirname(__file__))
    autofit_script = os.path.join(repo_root, "scripts", "auto_fit_reveal_boxes.py")
    preview_script = os.path.join(repo_root, "scripts", "draw_reveal_manifest_preview.py")
    out_dir = os.path.join(project.run_dir, "review")

    write_project_log(project, "step5_local_mask_start", source=source, manifest_path=manifest_path)
    refresh_unlocked_step5_boxes_from_template(project, manifest_path)
    try:
        fit_res = subprocess.run([
            sys.executable,
            autofit_script,
            "--manifest",
            manifest_path,
            "--repo-root",
            repo_root,
            "--search-margin",
            "24",
            "--max-area-ratio",
            "1.8",
        ], capture_output=True, text=True, encoding="utf-8", timeout=90)
    except subprocess.TimeoutExpired as exc:
        write_project_log(project, "step5_auto_fit_timeout", source=source, timeout_sec=90)
        raise HTTPException(status_code=504, detail="本地 Mask 自动标注超时，请检查上传图片是否过大或文件是否损坏") from exc

    if fit_res.returncode != 0:
        logger.error(f"Auto-fit reveal boxes failed: {fit_res.stderr}")
        write_project_log(
            project,
            "step5_auto_fit_error",
            source=source,
            returncode=fit_res.returncode,
            stdout=fit_res.stdout.strip(),
            stderr=fit_res.stderr.strip(),
        )
        raise HTTPException(status_code=500, detail="墨水框线自适应调整失败，请检查图片是否含有墨水或分镜配置是否正常")

    write_project_log(
        project,
        "step5_auto_fit_success",
        source=source,
        stdout=fit_res.stdout.strip(),
        stderr=fit_res.stderr.strip(),
    )

    try:
        prev_res = subprocess.run([
            sys.executable,
            preview_script,
            "--manifest",
            manifest_path,
            "--repo-root",
            repo_root,
            "--out-dir",
            out_dir,
        ], capture_output=True, text=True, encoding="utf-8", timeout=90)
    except subprocess.TimeoutExpired:
        write_project_log(project, "step5_preview_timeout", source=source, timeout_sec=90)
        return {"out_dir": out_dir, "preview_warning": "preview_timeout"}

    if prev_res.returncode != 0:
        logger.warning(f"Draw reveal manifest preview warned: {prev_res.stderr}")
        write_project_log(
            project,
            "step5_preview_warning",
            source=source,
            returncode=prev_res.returncode,
            stdout=prev_res.stdout.strip(),
            stderr=prev_res.stderr.strip(),
        )
    else:
        write_project_log(
            project,
            "step5_preview_success",
            source=source,
            stdout=prev_res.stdout.strip(),
        )

    return {"out_dir": out_dir, "fit_stdout": fit_res.stdout.strip(), "preview_stdout": prev_res.stdout.strip()}

@app.post("/api/projects/{project_id}/steps/3/confirm")
def confirm_images(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 步骤4：确认图片。将步骤 3 与 4 状态标记为已完成
    # 自动调用 write_reveal_manifest_template.py 生成 manifest 模板
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        template_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_reveal_manifest_template.py"))
        res = subprocess.run([
            sys.executable, template_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", timeout=90)
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            write_project_log(
                project,
                "step5_manifest_template_error",
                returncode=res.returncode,
                stdout=res.stdout.strip(),
                stderr=res.stderr.strip(),
            )
            raise HTTPException(status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常")
        write_project_log(project, "step5_manifest_template_created", stdout=res.stdout.strip())

    # 每次确认图片后都跑本地 Mask 自动标注，覆盖尚未手工确认的 auto-fit 框。
    run_step5_local_masking(project, manifest_path, source="confirm_images")
            
    handle_step_navigation(project, 4, db)
    return {"success": True}

# ==================== 步骤 5: Mask 自动标注与编辑 ====================

@app.post("/api/projects/{project_id}/steps/5/auto-mask")
def auto_mask_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请返回确认图片状态")
    run_step5_local_masking(project, manifest_path, source="manual_auto_mask")
    return {
        "success": True,
        "vision_used": False,
        "message": "已使用本地墨水自适应算法完成批量 Mask 标注，无需等待大模型 Vision 接口。",
    }

@app.get("/api/projects/{project_id}/steps/5/result")
def get_step5_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return {"success": False, "message": "尚未确认图片"}
        
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return {"success": True, "manifest": manifest}

@app.put("/api/projects/{project_id}/steps/5/result")
def update_step5_result(project_id: str, payload: Dict[str, Any], build_assets: bool = Query(True), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 保存手动编辑修改的 reveal_manifest
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    slide_count = len(payload.get("slides", [])) if isinstance(payload.get("slides"), list) else 0
    group_count = sum(
        len(slide.get("groups", []))
        for slide in payload.get("slides", [])
        if isinstance(slide, dict) and isinstance(slide.get("groups"), list)
    )
    write_project_log(project, "step5_save_manifest", slide_count=slide_count, group_count=group_count, build_assets=build_assets)

    if not build_assets:
        return {"success": True, "built_assets": False}

    # 人工保存后，校验并构建切层 assets，运行 build_reveal_scene.py
    build_scene_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_reveal_scene.py"))
    try:
        build_res = subprocess.run([
            sys.executable, build_scene_script, "--manifest", manifest_path
        ], capture_output=True, text=True, encoding="utf-8", timeout=120)
    except subprocess.TimeoutExpired as exc:
        write_project_log(project, "step5_build_scene_timeout", timeout_sec=120)
        raise HTTPException(status_code=504, detail="构建切层素材超时，请检查图片尺寸或标注框数量") from exc
    
    if build_res.returncode != 0:
        logger.error(f"Build reveal scene failed: {build_res.stderr}")
        write_project_log(
            project,
            "step5_build_scene_error",
            returncode=build_res.returncode,
            stdout=build_res.stdout.strip(),
            stderr=build_res.stderr.strip(),
        )
        raise HTTPException(status_code=500, detail=f"构建切层素材失败: {build_res.stderr}")

    write_project_log(project, "step5_build_scene_success", stdout=build_res.stdout.strip())
    handle_step_navigation(project, 5, db)
    return {"success": True, "built_assets": True}

# ==================== 步骤 6: 演讲稿编辑 ====================

@app.post("/api/projects/{project_id}/steps/6/init")
def init_step6_narration(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 如果不存在 narration，从 visual contract 自动导出初版
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请返回第二步生成分镜")
        
    write_narration_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_narration_from_visual_contract.py"))
    res = subprocess.run([
        sys.executable, write_narration_script, "--run-dir", project.run_dir, "--overwrite"
    ], capture_output=True, text=True, encoding="utf-8")
    
    if res.returncode != 0:
        logger.error(f"Init narration failed: {res.stderr}")
        raise HTTPException(status_code=500, detail="初始化演讲稿模版失败")
        
    # 合并各个 slide 独立的 narration_beats.json 到全局的 planning/narration_beats.json
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    global_slides = []
    for s in contract.get("slides", []):
        slide_id = s["slide_id"]
        slide_beat_path = os.path.join(project.run_dir, "slides", slide_id, "narration_beats.json")
        if os.path.exists(slide_beat_path):
            with open(slide_beat_path, "r", encoding="utf-8") as sf:
                s_data = json.load(sf)
                global_slides.append({
                    "slide_id": slide_id,
                    "beats": s_data.get("beats", [])
                })
        else:
            global_slides.append({
                "slide_id": slide_id,
                "beats": []
            })
            
    global_beats = {"slides": global_slides}
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(global_beats, f, ensure_ascii=False, indent=2)
        
    # 读回 narration_beats.json 展现给用户编辑
    with open(beats_path, "r", encoding="utf-8") as f:
        beats = json.load(f)
        
    return {"success": True, "beats": beats}

@app.get("/api/projects/{project_id}/steps/6/result")
def get_step6_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return {"success": False, "message": "演讲稿尚未生成"}
        
    with open(beats_path, "r", encoding="utf-8") as f:
        beats = json.load(f)
    return {"success": True, "beats": beats}

@app.put("/api/projects/{project_id}/steps/6/result")
def update_step6_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 保存全局规划下的 narration_beats.json
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    narration_lines = []
    tts_text_lines = []
    
    # 循环写入各 Slide 独立的 narration.txt, tts_text.txt 和 narration_beats.json
    for slide_data in payload.get("slides", []):
        slide_id = slide_data["slide_id"]
        slide_dir = os.path.join(project.run_dir, "slides", slide_id)
        os.makedirs(slide_dir, exist_ok=True)
        
        slide_beats = slide_data.get("beats", [])
        slide_narration = "\n".join(beat["spoken_text"] for beat in slide_beats)
        
        with open(os.path.join(slide_dir, "narration.txt"), "w", encoding="utf-8") as f:
            f.write(slide_narration + "\n")
        with open(os.path.join(slide_dir, "tts_text.txt"), "w", encoding="utf-8") as f:
            f.write(slide_narration + "\n")
        with open(os.path.join(slide_dir, "narration_beats.json"), "w", encoding="utf-8") as f:
            json.dump({"slide_id": slide_id, "beats": slide_beats}, f, ensure_ascii=False, indent=2)
            
        narration_lines.append(f"=== {slide_id} ===")
        tts_text_lines.append(f"=== {slide_id} ===")
        for beat in slide_beats:
            g_id = beat["group_id"]
            text = beat["spoken_text"]
            narration_lines.append(f"[{g_id}] {text}")
            tts_text_lines.append(text)
            
    narration_txt_path = os.path.join(project.run_dir, "planning", "narration.txt")
    tts_txt_path = os.path.join(project.run_dir, "planning", "tts_text.txt")
    
    with open(narration_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(narration_lines) + "\n")
    with open(tts_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(tts_text_lines) + "\n")
        
    # 运行校验，确保 narration 符合规范
    validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_narration_grounding.py"))
    val_res = subprocess.run([
        sys.executable, validate_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if val_res.returncode != 0:
        logger.warning(f"Narration grounding warned:\n{val_res.stderr}")
        
    handle_step_navigation(project, 6, db)
    return {"success": True}

# ==================== 步骤 7: 语音合成 ====================

@app.post("/api/projects/{project_id}/steps/7/synthesize")
def synthesize_tts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    tts_api_key = get_setting("tts_api_key")
    if not tts_api_key:
        tts_api_key = os.environ.get("MINIMAX_API_KEY")
        if tts_api_key:
            logger.info("已从系统环境变量中读取到 MINIMAX_API_KEY，将进行真实 TTS 合成")
            
    if not tts_api_key:
        raise HTTPException(status_code=400, detail="未配置 TTS 语音合成 API 密钥，且系统环境变量 MINIMAX_API_KEY 为空。")
        
    # 从 visual_contract 加载所有 slide_id
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请返回确认第二步状态")
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    slide_ids = [slide["slide_id"] for slide in contract.get("slides", [])]
    
    tts_endpoint = get_setting("tts_endpoint", "https://api.minimaxi.com/v1/t2a_v2") or "https://api.minimaxi.com/v1/t2a_v2"
    tts_model = get_setting("tts_model", "speech-2.8-hd") or "speech-2.8-hd"
    tts_voice_id = get_setting("tts_voice_id", "Chinese (Mandarin)_Soft_Girl") or "Chinese (Mandarin)_Soft_Girl"
    tts_speed = get_setting("tts_speed", "1.0") or "1.0"
    tts_volume = get_setting("tts_volume", "1.0") or "1.0"
    tts_pitch = get_setting("tts_pitch", "0") or "0"
    write_project_log(
        project,
        "step7_tts_start",
        slide_count=len(slide_ids),
        endpoint=tts_endpoint,
        model=tts_model,
        voice_id=tts_voice_id,
        timeout_sec=STEP7_TTS_TIMEOUT_SEC,
    )
        
    tts_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "minimax_tts.py"))
    
    # 循环对每一页 slide 分别生成音频
    for slide_id in slide_ids:
        text_file = os.path.join(project.run_dir, "slides", slide_id, "tts_text.txt")
        out_audio = os.path.join(project.run_dir, "slides", slide_id, "voice.mp3")
        out_meta = os.path.join(project.run_dir, "slides", slide_id, "tts_metadata.json")
        out_srt = os.path.join(project.run_dir, "slides", slide_id, "subtitles.srt")
        out_timeline = os.path.join(project.run_dir, "slides", slide_id, "audio_timeline.json")
        
        # 确保 text_file 存在，如果不存在，则从 contract 导出的 narration 中提取
        if not os.path.exists(text_file):
            logger.warning(f"tts_text.txt not found for slide {slide_id}, trying to generate it from contract")
            # 找到对应 slide 并提取 narration
            slide_narration = ""
            for s in contract.get("slides", []):
                if s.get("slide_id") == slide_id:
                    slide_narration = "\n".join(b["spoken_text"] for b in s.get("narration_beats", []))
                    break
            os.makedirs(os.path.dirname(text_file), exist_ok=True)
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(slide_narration + "\n")
                
        logger.info(f"Synthesizing TTS audio for slide: {slide_id}")
        write_project_log(project, "step7_slide_tts_start", slide_id=slide_id, text_file=text_file)
        tts_args = [
            sys.executable, tts_script,
            "--text-file", text_file,
            "--endpoint", tts_endpoint,
            "--api-key", tts_api_key,
            "--model", tts_model,
            "--voice-id", tts_voice_id,
            "--speed", tts_speed,
            "--volume", tts_volume,
            "--pitch", tts_pitch,
            "--timeout", str(STEP7_TTS_TIMEOUT_SEC),
            "--out-audio", out_audio,
            "--out-meta", out_meta,
            "--out-srt", out_srt,
            "--out-timeline", out_timeline,
            "--slide-id", slide_id
        ]
        
        try:
            started_at = time.monotonic()
            tts_res = subprocess.run(tts_args, capture_output=True, text=True, encoding="utf-8", timeout=STEP7_TTS_TIMEOUT_SEC + 15)
            elapsed = round(time.monotonic() - started_at, 3)
        except subprocess.TimeoutExpired as exc:
            write_project_log(project, "step7_slide_tts_timeout", slide_id=slide_id, timeout_sec=STEP7_TTS_TIMEOUT_SEC)
            raise HTTPException(status_code=504, detail=f"{slide_id} 语音合成超时，请检查 TTS 服务或稍后重试") from exc
        if tts_res.returncode != 0:
            logger.error(f"TTS Synthesis failed for {slide_id}: {tts_res.stderr}")
            write_project_log(
                project,
                "step7_slide_tts_error",
                slide_id=slide_id,
                returncode=tts_res.returncode,
                stdout=tts_res.stdout.strip(),
                stderr=tts_res.stderr.strip(),
            )
            raise HTTPException(status_code=500, detail=f"语音合成失败: {tts_res.stderr}")
        write_project_log(project, "step7_slide_tts_success", slide_id=slide_id, elapsed_sec=elapsed, stdout=tts_res.stdout.strip())
            
    # 合成完毕后，运行 bind_reveal_timeline.py 绑定时间轴
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    try:
        bind_res = subprocess.run([
            sys.executable, bind_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", timeout=STEP7_BIND_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        write_project_log(project, "step7_timeline_bind_timeout", timeout_sec=STEP7_BIND_TIMEOUT_SEC)
        raise HTTPException(status_code=504, detail="时间轴绑定超时") from exc
    
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed: {bind_res.stderr}")
        write_project_log(
            project,
            "step7_timeline_bind_error",
            returncode=bind_res.returncode,
            stdout=bind_res.stdout.strip(),
            stderr=bind_res.stderr.strip(),
        )
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")

    write_project_log(project, "step7_timeline_bind_success", stdout=bind_res.stdout.strip())
    handle_step_navigation(project, 7, db)
    return {"success": True}

# 获取音频文件接口（供前端试听）
@app.get("/api/projects/{project_id}/slides/{slide_id}/audio")
def get_slide_audio_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    audio_path = os.path.join(project.run_dir, "slides", slide_id, "voice.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="该页面音频尚未生成")
        
    from fastapi.responses import FileResponse
    return FileResponse(audio_path, media_type="audio/mp3")

# ==================== 步骤 8: 视频合成与渲染 ====================

@app.post("/api/projects/{project_id}/steps/8/render")
def render_video(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    render_started = time.time()
    write_project_log(project, "step8_render_start", run_dir=project.run_dir)

    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_started = time.time()
    write_project_log(project, "step8_timeline_bind_start", script=bind_script)
    try:
        bind_res = subprocess.run([
            sys.executable, bind_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        write_project_log(project, "step8_timeline_bind_timeout", timeout_sec=60)
        raise HTTPException(status_code=504, detail="渲染前绑定音频动画时间轴超时")

    if bind_res.returncode != 0:
        write_project_log(
            project,
            "step8_timeline_bind_error",
            returncode=bind_res.returncode,
            stderr=bind_res.stderr or "",
        )
        raise HTTPException(status_code=500, detail=f"渲染前绑定音频动画时间轴失败: {bind_res.stderr or ''}")

    write_project_log(
        project,
        "step8_timeline_bind_success",
        elapsed_sec=round(time.time() - bind_started, 3),
        stdout=(bind_res.stdout or "").strip(),
    )

    validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_run_assets.py"))
    validate_started = time.time()
    write_project_log(project, "step8_validate_assets_start", script=validate_script)
    try:
        validate_res = subprocess.run([
            sys.executable, validate_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        write_project_log(project, "step8_validate_assets_timeout", timeout_sec=60)
        raise HTTPException(status_code=504, detail="渲染前资产校验超时")

    if validate_res.returncode != 0:
        write_project_log(
            project,
            "step8_validate_assets_error",
            returncode=validate_res.returncode,
            stderr=validate_res.stderr or "",
        )
        raise HTTPException(status_code=500, detail=f"渲染前资产校验失败: {validate_res.stderr or ''}")

    write_project_log(
        project,
        "step8_validate_assets_success",
        elapsed_sec=round(time.time() - validate_started, 3),
        stdout=(validate_res.stdout or "").strip(),
    )

    # 首先调用 build_remotion_props.py 生成渲染配置属性
    build_props_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_remotion_props.py"))
    props_started = time.time()
    write_project_log(project, "step8_build_props_start", script=build_props_script)
    try:
        props_res = subprocess.run([
            sys.executable, build_props_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        write_project_log(project, "step8_build_props_timeout", timeout_sec=60)
        raise HTTPException(status_code=504, detail="构建 Remotion 配置超时")
    
    if props_res.returncode != 0:
        logger.error(f"Build remotion props failed: {props_res.stderr}")
        write_project_log(
            project,
            "step8_build_props_error",
            returncode=props_res.returncode,
            stderr=props_res.stderr or "",
        )
        raise HTTPException(status_code=500, detail=f"构建 Remotion 配置失败: {props_res.stderr or ''}")

    write_project_log(
        project,
        "step8_build_props_success",
        elapsed_sec=round(time.time() - props_started, 3),
        stdout=(props_res.stdout or "").strip(),
    )
        
    # 接着，执行 Remotion 渲染
    # 检测 Node.js 模块依赖，执行 npm install (如果 node_modules 不存在)
    remotion_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "remotion"))
    node_modules_dir = os.path.join(remotion_dir, "node_modules")
    
    if not os.path.exists(node_modules_dir):
        logger.info("Initializing Remotion node_modules, running npm install...")
        npm_started = time.time()
        write_project_log(project, "step8_npm_install_start", cwd=remotion_dir)
        # Windows 环境下运行 npm.cmd
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            npm_install = subprocess.run(
                [npm_cmd, "install"],
                cwd=remotion_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            logger.error("npm install for Remotion timed out")
            write_project_log(project, "step8_npm_install_timeout", timeout_sec=300)
            raise HTTPException(status_code=504, detail="初始化 Remotion Node 依赖超时")
        if npm_install.returncode != 0:
            logger.error(f"npm install failed:\n{npm_install.stderr}")
            write_project_log(
                project,
                "step8_npm_install_error",
                returncode=npm_install.returncode,
                stderr=npm_install.stderr or "",
            )
            raise HTTPException(status_code=500, detail=f"初始化 Remotion Node 依赖失败: {npm_install.stderr or ''}")
        write_project_log(
            project,
            "step8_npm_install_success",
            elapsed_sec=round(time.time() - npm_started, 3),
            stdout=(npm_install.stdout or "").strip(),
        )
    else:
        write_project_log(project, "step8_npm_install_skipped", node_modules_dir=node_modules_dir)
            
    # 调用 PowerShell 执行 render_remotion.ps1
    # 或者是直接用 npx remotion render
    # 原项目有 render_remotion.ps1 渲染脚本：
    # param($RunId, $RepoRoot = ".")
    # 我们直接使用 python 子进程调用 powershell 跑渲染脚本，或者将其核心命令直接通过 Node 跑：
    # npx remotion render RevealVideo out.mp4 --props="<path_to_props>"
    # 我们来看一下 scripts/render_remotion.ps1
    # 它实际上执行了：
    # npx remotion render RevealVideo "runs/$RunId/out.mp4" --props="runs/$RunId/remotion_props.json"
    # 我们直接用 subprocess.run 调用 npx
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    props_json_path = os.path.join(project.run_dir, "remotion_props.json")
    output_mp4_path = os.path.join(project.run_dir, "out.mp4")
    
    logger.info(f"Starting Remotion render for {project_id}...")
    render_args = [
        npx_cmd, "remotion", "render", "src/index.tsx", "ArticleVideo",
        output_mp4_path, f"--props={props_json_path}"
    ]
    remotion_started = time.time()
    write_project_log(
        project,
        "step8_remotion_render_start",
        cwd=remotion_dir,
        output_path=output_mp4_path,
        props_path=props_json_path,
        args=render_args,
    )
    
    try:
        render_res = subprocess.run(
            render_args,
            cwd=remotion_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        logger.error("Remotion render timed out")
        write_project_log(project, "step8_remotion_render_timeout", timeout_sec=900)
        raise HTTPException(status_code=504, detail="视频渲染超时")

    if render_res.returncode != 0:
        logger.error(f"Remotion render failed: {render_res.stderr}")
        write_project_log(
            project,
            "step8_remotion_render_error",
            returncode=render_res.returncode,
            stderr=render_res.stderr or "",
        )
        raise HTTPException(status_code=500, detail=f"视频渲染失败: {render_res.stderr or ''}")

    output_size = os.path.getsize(output_mp4_path) if os.path.exists(output_mp4_path) else 0
    write_project_log(
        project,
        "step8_remotion_render_success",
        elapsed_sec=round(time.time() - remotion_started, 3),
        output_path=output_mp4_path,
        output_size=output_size,
        stdout=(render_res.stdout or "").strip(),
    )
        
    handle_step_navigation(project, 8, db)
    write_project_log(
        project,
        "step8_render_completed",
        elapsed_sec=round(time.time() - render_started, 3),
        video_url=f"/api/projects/{project_id}/video",
    )
    return {"success": True, "video_url": f"/api/projects/{project_id}/video"}

# 获取最终生成的 MP4 视频
@app.get("/api/projects/{project_id}/video/status")
def get_final_video_status(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    video_path = os.path.join(project.run_dir, "out.mp4")
    exists = os.path.exists(video_path)
    video_mtime = os.path.getmtime(video_path) if exists else 0
    latest_input_mtime = 0
    latest_input_path = None

    input_candidates = [
        os.path.join(project.run_dir, "reveal_manifest.json"),
        os.path.join(project.run_dir, "planning", "visual_contract.json"),
    ]
    slides_dir = os.path.join(project.run_dir, "slides")
    if os.path.isdir(slides_dir):
        for root, _, files in os.walk(slides_dir):
            for filename in files:
                if filename.lower().endswith((".json", ".mp3", ".srt", ".png", ".jpg", ".jpeg")):
                    input_candidates.append(os.path.join(root, filename))

    for path in input_candidates:
        if not os.path.exists(path):
            continue
        mtime = os.path.getmtime(path)
        if mtime > latest_input_mtime:
            latest_input_mtime = mtime
            latest_input_path = path

    stale = bool(exists and latest_input_mtime > video_mtime + 1)
    return {
        "exists": exists,
        "video_url": f"/api/projects/{project_id}/video" if exists else None,
        "size": os.path.getsize(video_path) if exists else 0,
        "updated_at": datetime.fromtimestamp(video_mtime).isoformat(timespec="seconds") if exists else None,
        "stale": stale,
        "latest_input_updated_at": datetime.fromtimestamp(latest_input_mtime).isoformat(timespec="seconds") if latest_input_mtime else None,
        "latest_input_path": latest_input_path,
    }

@app.get("/api/projects/{project_id}/video")
def get_final_video(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    video_path = os.path.join(project.run_dir, "out.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="最终视频尚未渲染生成")
        
    from fastapi.responses import FileResponse
    return FileResponse(video_path, media_type="video/mp4")

# ==================== 前端托管 ====================

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
os.makedirs(static_dir, exist_ok=True)

# 挂载静态资源
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # 本地局域网启动，默认端口 8000
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
