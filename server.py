import os
import io
import sys
import uuid
import json
import shutil
import logging
import subprocess
import re
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

def get_openai_client(api_key: str, base_url: str = None) -> OpenAI:
    # 强制不使用环境变量中的代理，防止某些局域网代理的 SSL 拦截规则冲突
    # 并强制定义 User-Agent 为 Chrome 浏览器以绕过 Cloudflare WAF/JA3 爬虫过滤指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    http_client = httpx.Client(
        limits=limits,
        trust_env=False,
        headers=headers
    )
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

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
            
    current_status[str(target_step)] = "completed"
    project.current_step = target_step
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
    
    client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
    system_prompt = "你是一个专业的内容提炼助手。请阅读用户输入的 Markdown 文章，提炼出它的核心标题以及一份易于视频分镜表达的摘要提纲（150字以内）。请直接返回 JSON 格式结果，格式为: {\"title\": \"标题\", \"summary\": \"提炼好的摘要提纲\", \"content\": \"原文\"}"
    
    try:
        response = client.chat.completions.create(
            model=llm_model,
            temperature=llm_temp,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )
        content_str = response.choices[0].message.content.strip()
        cleaned_content = clean_json_markdown(content_str)
        brief = json.loads(cleaned_content)
        brief["content"] = content
    except Exception as e:
        logger.error(f"LLM ingest article error: {e}")
        raise HTTPException(status_code=500, detail=f"文章提炼失败: {str(e)}")
            
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
        
    handle_step_navigation(project, 1, db)
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
        
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
        
    # 加载已有的 visual_contract 架构 schema 做指导
    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "schemas", "visual_contract.schema.json"))
    schema_hint = ""
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_hint = f.read()
            
    system_prompt = f"""你是一个顶级的 PPT 视频分镜策划师。
请阅读用户输入的内容摘要和全文，设计出一份符合 PPT 动画视频制作标准的视觉合约(Visual Contract)。
视频的画面风格为“温暖极简手绘线稿风”。
要求：
1. 必须要将整篇文章合理划分，分成 8 到 14 页 Slide（每页的 slide_id 为 slide_001, slide_002 格式）。
2. 每页 Slide 必须定义 5-8 个视觉分组(visual_groups)，包含：
   - 1个 title 主标题（role 为 'title'）
   - 1个 subtitle 副标题（role 为 'subtitle'）
   - 2-4个 body/diagram 主体/图表区（role 只能是 'content_body', 'diagram', 'annotation', 'summary', 'decoration' 之一）
   - 1个 summary 总结区（role 为 'summary'）
3. 每个视觉分组（visual_groups）必须有：
   - id: 比如 title_group, subtitle_group, body_group_01 等
   - visible_text: 页面上会显式画出来的中文字符标签（非常重要，通常为 2-8 个字，绝对不能空）
   - visual_anchor: 手绘线稿元素的视觉描述（比如“顶部主标题”、“左边带圆圈数字1的方框”、“中间一个简笔画小脑”）
   - narration_function: 解释该分组在画面中所起的视觉/解释作用
   - reveal_order: 页面渲染时层淡入淡出显示的顺序，从 1 开始依次增加
4. 必须规划 narration_beats (旁白语段)，使说话声音与相应视觉分组绑定：
   - group_id: 指向前面定义的 visual_groups 中的 id
   - visible_anchor: 该分组对应的 visible_text 文本（不可写错，必须一致）
   - spoken_intent: 这一句话想达到的意图
   - spoken_text: 这一句话具体要朗读的中文旁白（需自然连贯，解释 visible_text）
5. 请确保生成的 JSON 数据严格符合以下的 JSON Schema 格式要求：
{schema_hint}

请直接返回合法的 JSON 对象，不要包含 markdown 标记的 ```json 外壳。"""

    try:
        client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=llm_temp,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"项目主题：{brief['title']}\n摘要提纲：{brief['summary']}\n正文全文：\n{brief['content']}"}
                ]
            )
        except Exception as inner_e:
            logger.warning(f"Failed LLM call with response_format in step 2, retrying without it: {inner_e}")
            response = client.chat.completions.create(
                model=llm_model,
                temperature=llm_temp,
                messages=[
                    {"role": "system", "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块标记（如 ```json ）。"},
                    {"role": "user", "content": f"项目主题：{brief['title']}\n摘要提纲：{brief['summary']}\n正文全文：\n{brief['content']}"}
                ]
            )
            
        content_str = response.choices[0].message.content.strip()
        cleaned_content = clean_json_markdown(content_str)
        contract = json.loads(cleaned_content)
        
        # 强制补充一些固定版本信息
        contract["version"] = "visual_contract_v1"
        if "topic" not in contract:
            contract["topic"] = {
                "topic_id": "topic_" + project_id,
                "topic_name": brief["title"],
                "topic_summary": brief["summary"]
            }
            
        # 写入 JSON
        contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
        with open(contract_path, "w", encoding="utf-8") as f:
            json.dump(contract, f, ensure_ascii=False, indent=2)
            
        # 调用原项目的验证脚本进行 contract 校验
        validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_visual_contract.py"))
        val_res = subprocess.run([
            sys.executable, validate_script, "--contract", contract_path
        ], capture_output=True, text=True, encoding="utf-8")
        
        if val_res.returncode != 0:
            logger.warning(f"Visual contract validation warning:\n{val_res.stderr}")
            # 虽然校验可能报错，但如果不严重，仍然保存以方便用户在前台手动修改
            
        handle_step_navigation(project, 2, db)
        return {"success": True, "contract": contract}
    except Exception as e:
        logger.error(f"LLM write visual contract error: {e}")
        raise HTTPException(status_code=500, detail=f"LLM 规划分镜失败: {str(e)}")

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
    group_lines = []
    for idx, g in enumerate(slide.get("visual_groups", []), start=1):
        group_lines.append(
            f"{idx}. group_id={g.get('id')}; role={g.get('role')}; "
            f"exact visible Chinese label='{g.get('visible_text', '')}'; "
            f"visual anchor='{g.get('visual_anchor', '')}'."
        )
    groups_str = "\n".join(group_lines)
    main_title = slide.get("main_title", "")
    subtitle = slide.get("subtitle", "")
    subtitle_part = f"Subtitle: '{subtitle}'. " if subtitle else ""
    return (
        f"Create one 16:9 PPT-style whiteboard slide for topic '{topic_name}'. "
        f"Title: '{main_title}'. {subtitle_part}\n"
        "CRITICAL composition rules:\n"
        "1. Render every visual group below as a separate visual island with clean whitespace between groups.\n"
        "2. The exact visible Chinese label for each group must appear legibly in the image. Do not replace, paraphrase, or omit labels.\n"
        "3. Do not merge two groups into one drawing. Do not let group drawings overlap. Keep at least 80 px of clean background between independent body groups.\n"
        "4. Title stays at the top, subtitle directly below it, body groups in the middle, summary above the subtitle-safe area.\n"
        "5. Reserve the bottom 150 px of the 1920x1080 canvas for subtitles: keep y=930..1080 clean, with no important text, labels, faces, or key drawings.\n"
        "6. Use short labels and simple hand-drawn shapes; avoid decorative marks that connect separate groups.\n\n"
        f"Visual groups to draw:\n{groups_str}\n\n"
        "Style: warm minimalist hand-drawn vector line art, uniform #FFFDF7 background, black ink #111111, "
        "single yellow highlight #F9D65C, clean whiteboard sketch, no shadows, no gradients, no paper texture."
    )
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
        ], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            raise HTTPException(status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常")
            
        # 预先执行 auto_fit_reveal_boxes.py 进行算法自适应黑墨水对齐
        autofit_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "auto_fit_reveal_boxes.py"))
        fit_res = subprocess.run([
            sys.executable, autofit_script, "--manifest", manifest_path
        ], capture_output=True, text=True, encoding="utf-8")
        if fit_res.returncode != 0:
            logger.warning(f"Initial auto-fit reveal boxes warning: {fit_res.stderr}")
            
    handle_step_navigation(project, 4, db)
    return {"success": True}

# ==================== 步骤 5: Mask 自动标注与编辑 ====================

NARRATION_SPLIT_RE = re.compile(r"[^，,。！？!?；;：:\n]+[，,。！？!?；;：:]?")

ROLE_LABELS = {
    "title": "主标题",
    "subtitle": "副标题",
    "summary": "总结区",
    "diagram": "图示",
    "annotation": "注释",
    "decoration": "装饰元素",
    "content_body": "正文内容",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(str(role or "").strip(), "正文内容")


def split_narration_text(text: str) -> List[str]:
    value = str(text or "").strip()
    if not value:
        return []
    parts = NARRATION_SPLIT_RE.findall(value) or [value]
    return [part.strip() for part in parts if part.strip()]


def build_narration_fragments(contract_slide: Dict[str, Any]) -> List[Dict[str, Any]]:
    fragments: List[Dict[str, Any]] = []
    for beat_idx, beat in enumerate(contract_slide.get("narration_beats", []) or []):
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or f"beat_{beat_idx + 1}").strip()
        group_id = str(beat.get("group_id") or "").strip()
        for frag_idx, text in enumerate(split_narration_text(str(beat.get("spoken_text", ""))), start=1):
            fragments.append({
                "id": f"{beat_id}::{frag_idx}",
                "beat_id": beat_id,
                "group_id": group_id,
                "beat_index": beat_idx,
                "fragment_index": frag_idx - 1,
                "order": len(fragments) + 1,
                "text": text,
            })
    return fragments


def box_to_xyxy(box: Any) -> List[int]:
    if isinstance(box, dict):
        x = int(round(float(box.get("x", 860))))
        y = int(round(float(box.get("y", 460))))
        w = int(round(float(box.get("w", 200))))
        h = int(round(float(box.get("h", 160))))
        return [x, y, max(x + 1, x + w), max(y + 1, y + h)]
    if isinstance(box, list) and len(box) >= 4:
        return [int(round(float(v))) for v in box[:4]]
    return [860, 460, 1060, 620]


def group_has_paint(group: Dict[str, Any]) -> bool:
    manual_mask = group.get("manual_mask")
    if not isinstance(manual_mask, dict):
        return False
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list):
        return False
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        mode = str(stroke.get("mode", "")).lower()
        if not stroke.get("eraser") and mode != "erase" and stroke.get("points"):
            return True
    return False


def semantic_block_payload(
    slide_id: str,
    index: int,
    fragment_ids: List[str],
    visual_group_id: str,
    group: Optional[Dict[str, Any]],
    fragments_by_id: Dict[str, Dict[str, Any]],
    existing_box: Any = None,
    ai_block: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ai_block = ai_block or {}
    selected_fragments = [fragments_by_id[fid] for fid in fragment_ids if fid in fragments_by_id]
    beat_ids = []
    narration_group_ids = []
    for fragment in selected_fragments:
        if fragment.get("beat_id") and fragment["beat_id"] not in beat_ids:
            beat_ids.append(fragment["beat_id"])
        if fragment.get("group_id") and fragment["group_id"] not in narration_group_ids:
            narration_group_ids.append(fragment["group_id"])
    role = str((group or {}).get("role") or "content_body")
    visible_text = str((group or {}).get("visible_text") or ai_block.get("text_label") or f"语块 {index}").strip()
    visual_anchor = str((group or {}).get("visual_anchor") or "").strip()
    semantic_type = str(ai_block.get("semantic_element_type") or role_label(role)).strip()
    visual_description = str(ai_block.get("visual_description") or "").strip()
    if not visual_description:
        if visual_anchor and visible_text:
            visual_description = f"{semantic_type}：画面中可见文字“{visible_text}”，位置/形态为{visual_anchor}。"
        elif visual_anchor:
            visual_description = f"{semantic_type}：{visual_anchor}。"
        else:
            visual_description = f"{semantic_type}：请结合当前页画面中与旁白含义最接近的可见元素。"
    semantic_note = str(ai_block.get("semantic_note") or "").strip()
    if not semantic_note:
        semantic_note = "建议只涂抹该语块对应的可见元素本体，避开相邻箭头、装饰线和底部字幕安全区。"
    return {
        "group_id": f"semantic_{slide_id}_{index:02d}",
        "source": "ai_semantic",
        "visual_group_id": visual_group_id,
        "role": role,
        "text_label": visible_text or f"语块 {index}",
        "visual_anchor": visual_anchor,
        "semantic_element_type": semantic_type,
        "visual_description": visual_description,
        "semantic_note": semantic_note,
        "semantic_confidence": ai_block.get("confidence"),
        "narration_beat_id": beat_ids[0] if beat_ids else "",
        "narration_beat_ids": beat_ids,
        "narration_group_id": narration_group_ids[0] if narration_group_ids else visual_group_id,
        "narration_fragments": [
            {
                "id": fragment["id"],
                "beat_id": fragment.get("beat_id", ""),
                "group_id": fragment.get("group_id", ""),
                "text": fragment.get("text", ""),
            }
            for fragment in selected_fragments
        ],
        "spoken_text": "".join(fragment.get("text", "") for fragment in selected_fragments),
        "manual_mask": {"color": "", "strokes": []},
        "box": box_to_xyxy(existing_box),
    }


def deterministic_semantic_blocks(
    slide_id: str,
    contract_slide: Dict[str, Any],
    manifest_slide: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups = {
        str(group.get("id", "")).strip(): group
        for group in (contract_slide.get("visual_groups") or [])
        if isinstance(group, dict) and str(group.get("id", "")).strip()
    }
    existing_boxes = {}
    if manifest_slide:
        for group in manifest_slide.get("groups", []) or []:
            if isinstance(group, dict):
                existing_boxes[str(group.get("id") or group.get("group_id") or "")] = group.get("box")
    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {fragment["id"]: fragment for fragment in fragments}
    beat_to_fragments: Dict[str, List[str]] = {}
    for fragment in fragments:
        beat_to_fragments.setdefault(fragment["beat_id"], []).append(fragment["id"])
    blocks: List[Dict[str, Any]] = []
    for beat in contract_slide.get("narration_beats", []) or []:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        group_id = str(beat.get("group_id") or "").strip()
        fragment_ids = beat_to_fragments.get(beat_id) or []
        if not fragment_ids:
            continue
        group = groups.get(group_id)
        blocks.append(semantic_block_payload(
            slide_id,
            len(blocks) + 1,
            fragment_ids,
            group_id,
            group,
            fragments_by_id,
            existing_boxes.get(group_id),
        ))
    return blocks


def semantic_blocks_from_ai(
    slide_id: str,
    ai_data: Dict[str, Any],
    contract_slide: Dict[str, Any],
    manifest_slide: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups = {
        str(group.get("id", "")).strip(): group
        for group in (contract_slide.get("visual_groups") or [])
        if isinstance(group, dict) and str(group.get("id", "")).strip()
    }
    existing_boxes = {}
    if manifest_slide:
        for group in manifest_slide.get("groups", []) or []:
            if isinstance(group, dict):
                existing_boxes[str(group.get("id") or group.get("group_id") or "")] = group.get("box")
    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {fragment["id"]: fragment for fragment in fragments}
    by_beat_id: Dict[str, List[str]] = {}
    by_group_id: Dict[str, List[str]] = {}
    for fragment in fragments:
        by_beat_id.setdefault(fragment.get("beat_id", ""), []).append(fragment["id"])
        by_group_id.setdefault(fragment.get("group_id", ""), []).append(fragment["id"])
    blocks: List[Dict[str, Any]] = []
    used_fragment_ids = set()
    for raw_block in ai_data.get("blocks", []) if isinstance(ai_data.get("blocks"), list) else []:
        if not isinstance(raw_block, dict):
            continue
        fragment_ids = [
            str(value).strip()
            for value in raw_block.get("fragment_ids", [])
            if str(value).strip() in fragments_by_id and str(value).strip() not in used_fragment_ids
        ] if isinstance(raw_block.get("fragment_ids"), list) else []
        beat_id = str(raw_block.get("narration_beat_id") or raw_block.get("beat_id") or "").strip()
        if not fragment_ids and beat_id:
            fragment_ids = [fid for fid in by_beat_id.get(beat_id, []) if fid not in used_fragment_ids]
        visual_group_id = str(raw_block.get("visual_group_id") or raw_block.get("group_id") or "").strip()
        if not fragment_ids and visual_group_id:
            fragment_ids = [fid for fid in by_group_id.get(visual_group_id, []) if fid not in used_fragment_ids]
        if not fragment_ids:
            continue
        if not visual_group_id:
            visual_group_id = fragments_by_id[fragment_ids[0]].get("group_id", "")
        group = groups.get(visual_group_id)
        blocks.append(semantic_block_payload(
            slide_id,
            len(blocks) + 1,
            fragment_ids,
            visual_group_id,
            group,
            fragments_by_id,
            existing_boxes.get(visual_group_id),
            raw_block,
        ))
        used_fragment_ids.update(fragment_ids)
    if len(used_fragment_ids) < len(fragments):
        fallback = deterministic_semantic_blocks(slide_id, contract_slide, manifest_slide)
        for block in fallback:
            fragment_ids = [fragment["id"] for fragment in block.get("narration_fragments", [])]
            if any(fid not in used_fragment_ids for fid in fragment_ids):
                blocks.append({
                    **block,
                    "group_id": f"semantic_{slide_id}_{len(blocks) + 1:02d}",
                })
                used_fragment_ids.update(fragment_ids)
    return blocks

@app.post("/api/projects/{project_id}/steps/5/auto-mask")
def auto_mask_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请返回确认图片状态")
        
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    vision_model = get_setting("vision_model", "gpt-4o")
    
    # 获取每一页的图片和 visual groups 以调用 Vision API 进行自动标注
    vision_used = False
    if not llm_api_key:
        logger.warning("No LLM API Key configured, skipping vision-assisted auto masking. Running auto-fit fallback.")
    else:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                
            client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
            import base64
            
            for slide in manifest.get("slides", []):
                slide_id = slide["slide_id"]
                img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
                if not os.path.exists(img_path):
                    continue
                    
                # 优化：将生图大分辨率在后端等比缩放到 960 宽，规避 Vision API 发送 Base64 消息体过大（Payload 413）或接口超时问题
                vision_width = 1920
                vision_height = 1080
                with open(img_path, "rb") as image_file:
                    try:
                        from PIL import Image
                        img = Image.open(image_file)
                        if img.width > 960:
                            ratio = 960 / img.width
                            new_h = int(img.height * ratio)
                            img = img.resize((960, new_h), Image.Resampling.LANCZOS)
                        vision_width, vision_height = img.width, img.height
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        base64_image = base64.b64encode(buf.getvalue()).decode('utf-8')
                    except Exception as resize_err:
                        logger.warning(f"Resize image failed for auto-mask {slide_id}: {resize_err}")
                        image_file.seek(0)
                        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                    
                # 拼接分组信息。当前 reveal manifest 使用 groups[]，
                # 旧版 reveal_boxes[] 仅作为兼容兜底。
                groups_info = []
                slide_groups = slide.get("groups") if isinstance(slide.get("groups"), list) else []
                if slide_groups:
                    for group in slide_groups:
                        box = group.get("box", {}) if isinstance(group.get("box"), dict) else {}
                        scaled_box = [
                            round(float(box.get("x", 0)) * vision_width / 1920),
                            round(float(box.get("y", 0)) * vision_height / 1080),
                            round((float(box.get("x", 0)) + float(box.get("w", 0))) * vision_width / 1920),
                            round((float(box.get("y", 0)) + float(box.get("h", 0))) * vision_height / 1080),
                        ]
                        groups_info.append(
                            f"Group ID: {group['id']}\n"
                            f"- exact visible label: {group.get('visible_text', '')}\n"
                            f"- visual anchor: {group.get('visual_anchor', '')}\n"
                            f"- prior box on the provided image: {scaled_box}"
                        )
                else:
                    for box in slide.get("reveal_boxes", []):
                        groups_info.append(f"Group ID: {box['group_id']}, text label: '{box.get('text_label', '')}'")
                groups_info_str = "\n".join(groups_info)
                if not groups_info_str:
                    continue
                
                system_prompt = (
                    "You are a precise visual segmentation annotator for a PPT-style whiteboard slide. "
                    f"The provided image is {vision_width}x{vision_height}. "
                    "For each group, locate ONLY the visual island that semantically belongs to that group. "
                    "Use the exact visible label and visual anchor to identify the correct island. "
                    "Return tight, minimal bounding boxes; do not include unrelated neighboring drawings, arrows, subtitles, or summary text. "
                    "Boxes should not overlap except for a tiny unavoidable edge touch. If two groups are close, split them at the whitespace boundary. "
                    f"The coordinates must be in the provided image coordinate system: X 0..{vision_width}, Y 0..{vision_height}. "
                    "Return a JSON object in this format: "
                    "{\"boxes\": [{\"group_id\": \"group_id\", \"box\": [x_min, y_min, x_max, y_max]}]}"
                )
                
                user_msg = (
                    f"Please find the coordinates of the bounding boxes containing these specific text labels or graphics in the 1920x1080 image:\n"
                    f"{groups_info_str}"
                )
                
                try:
                    response = client.chat.completions.create(
                        model=vision_model,
                        response_format={"type": "json_object"},
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_msg},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                except Exception as inner_e:
                    logger.warning(f"Failed Vision call with response_format, retrying without it: {inner_e}")
                    response = client.chat.completions.create(
                        model=vision_model,
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt + " Please return ONLY raw JSON without any markdown block wrappers like ```json."},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_msg},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                try:
                    resp_content = response.choices[0].message.content.strip()
                    cleaned_content = clean_json_markdown(resp_content)
                    vision_data = json.loads(cleaned_content)
                    boxes_dict = {b["group_id"]: b["box"] for b in vision_data.get("boxes", [])}
                    
                    if slide_groups:
                        for group in slide_groups:
                            g_id = group["id"]
                            if g_id in boxes_dict:
                                raw_x1, raw_y1, raw_x2, raw_y2 = [float(v) for v in boxes_dict[g_id]]
                                x1 = int(round(raw_x1 * 1920 / vision_width))
                                y1 = int(round(raw_y1 * 1080 / vision_height))
                                x2 = int(round(raw_x2 * 1920 / vision_width))
                                y2 = int(round(raw_y2 * 1080 / vision_height))
                                group["box"] = {
                                    "x": max(0, x1),
                                    "y": max(0, y1),
                                    "w": max(1, x2 - x1),
                                    "h": max(1, y2 - y1)
                                }
                    else:
                        for box in slide.get("reveal_boxes", []):
                            g_id = box["group_id"]
                            if g_id in boxes_dict:
                                box["box"] = [int(v) for v in boxes_dict[g_id]]
                except Exception as ex:
                    logger.error(f"Failed to parse vision response for slide {slide_id}: {ex}. Content: {response.choices[0].message.content}")
                    
            # 保存更新后的 manifest
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            vision_used = True
                
        except Exception as e:
            logger.error(f"Vision assisted auto-masking failed: {e}. Will fallback to deterministic scripts.")
            vision_used = False
            
    # 接着运行 auto_fit_reveal_boxes.py 做黑墨水自适应边界修剪
    autofit_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "auto_fit_reveal_boxes.py"))
    fit_res = subprocess.run([
        sys.executable, autofit_script, "--manifest", manifest_path
    ], capture_output=True, text=True, encoding="utf-8")
    
    if fit_res.returncode != 0:
        logger.error(f"Auto-fit reveal boxes failed: {fit_res.stderr}")
        raise HTTPException(status_code=500, detail="墨水框线自适应调整失败，请检查图片是否含有墨水")
        
    # 生成预览图片
    preview_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "draw_reveal_manifest_preview.py"))
    out_dir = os.path.join(project.run_dir, "review")
    prev_res = subprocess.run([
        sys.executable, preview_script, "--manifest", manifest_path, "--out-dir", out_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if prev_res.returncode != 0:
        logger.warning(f"Draw reveal manifest preview warned: {prev_res.stderr}")
        
    if vision_used:
        msg = f"视觉识别（{vision_model}）成功完成，已精确定位所有分组包围框。"
    else:
        msg = "未启用视觉识别（未配置 API Key 或识别失败），已使用墨水自适应算法自动对齐包围框。"
        
    return {"success": True, "vision_used": vision_used, "message": msg}

@app.post("/api/projects/{project_id}/steps/5/semantic-blocks")
def semantic_blocks_project(project_id: str, payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请先确认图片")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请先生成分镜")

    payload = payload or {}
    requested_slide_id = str(payload.get("slide_id") or "").strip()

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    contract_slides = {
        str(slide.get("slide_id", "")).strip(): slide
        for slide in contract.get("slides", [])
        if isinstance(slide, dict) and str(slide.get("slide_id", "")).strip()
    }
    target_slides = []
    for slide in manifest.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        if requested_slide_id and slide_id != requested_slide_id:
            continue
        if slide_id in contract_slides:
            target_slides.append(slide)
    if requested_slide_id and not target_slides:
        raise HTTPException(status_code=404, detail=f"找不到当前页分镜：{requested_slide_id}")

    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    vision_model = get_setting("vision_model", "gpt-4o")
    client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url) if llm_api_key else None
    vision_used = False
    processed_count = 0

    for manifest_slide in target_slides:
        slide_id = str(manifest_slide.get("slide_id", "")).strip()
        contract_slide = contract_slides[slide_id]
        semantic_blocks = []
        img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")

        if client and os.path.exists(img_path):
            try:
                import base64

                with Image.open(img_path) as img:
                    if img.width > 960:
                        ratio = 960 / img.width
                        img = img.resize((960, int(img.height * ratio)), Image.Resampling.LANCZOS)
                    vision_width, vision_height = img.width, img.height
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    base64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

                fragments = build_narration_fragments(contract_slide)
                fragment_lines = "\n".join(
                    f"- {fragment['id']} / 序号{fragment['order']} / group={fragment['group_id']}: {fragment['text']}"
                    for fragment in fragments
                )
                group_lines = "\n".join(
                    f"- {group.get('id')}: role={role_label(str(group.get('role', 'content_body')))}, "
                    f"visible_text={group.get('visible_text', '')}, visual_anchor={group.get('visual_anchor', '')}, "
                    f"function={group.get('narration_function', '')}"
                    for group in contract_slide.get("visual_groups", []) or []
                    if isinstance(group, dict)
                )
                system_prompt = (
                    "你是 PPT 视频 Mask 标注前的语义分块助手。"
                    "你只做预识别：把演讲旁白片段和当前画面中实际可见的元素对应起来，帮助用户后续手动画 Mask。"
                    "不要输出坐标，不要生成矩形框，不要声称已经完成 Mask。"
                    "每个语块必须对应一个或多个连续旁白片段，并描述画面中可见的元素是什么，"
                    "需要说明它是主标题、副标题、正文、图示、总结区或其他可见元素。"
                    "画面内容描述要具体到用户知道应该涂抹哪里。"
                    "返回严格 JSON："
                    "{\"blocks\":[{\"fragment_ids\":[\"beat_01::1\"],\"visual_group_id\":\"body_group_01\","
                    "\"semantic_element_type\":\"正文内容\",\"visual_description\":\"画面中央...\","
                    "\"semantic_note\":\"建议涂抹...\",\"confidence\":0.8}]}"
                )
                user_text = (
                    f"当前图片尺寸：{vision_width}x{vision_height}\n"
                    f"Slide ID：{slide_id}\n\n"
                    f"演讲旁白片段：\n{fragment_lines}\n\n"
                    f"分镜里的可见元素候选：\n{group_lines}\n\n"
                    "请根据图片和分镜，生成适合人工涂抹的语义块清单。"
                )
                try:
                    response = client.chat.completions.create(
                        model=vision_model,
                        response_format={"type": "json_object"},
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                                ],
                            },
                        ],
                    )
                except Exception as inner_e:
                    logger.warning(f"Semantic block Vision call with response_format failed, retrying raw JSON: {inner_e}")
                    response = client.chat.completions.create(
                        model=vision_model,
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块。"},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                                ],
                            },
                        ],
                    )
                raw_content = response.choices[0].message.content.strip()
                ai_data = json.loads(clean_json_markdown(raw_content))
                semantic_blocks = semantic_blocks_from_ai(slide_id, ai_data, contract_slide, manifest_slide)
                vision_used = True
            except Exception as exc:
                logger.warning(f"AI semantic split failed for {slide_id}, using deterministic fallback: {exc}")

        if not semantic_blocks:
            semantic_blocks = deterministic_semantic_blocks(slide_id, contract_slide, manifest_slide)

        painted_groups = [
            group for group in manifest_slide.get("groups", []) or []
            if isinstance(group, dict) and group_has_paint(group)
        ]
        manifest_slide["semantic_blocks"] = semantic_blocks
        manifest_slide["groups"] = painted_groups
        manifest_slide["reveal_boxes"] = [
            box for box in manifest_slide.get("reveal_boxes", []) or []
            if isinstance(box, dict) and group_has_paint(box)
        ]
        manifest_slide["status"] = "pending"
        processed_count += 1

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    msg = "AI 语义分块完成：已生成旁白与画面内容清单，请按清单手动涂抹 Mask。"
    if not vision_used:
        msg = "已根据分镜合约生成语义分块草稿；配置视觉模型后可结合当前画面做更细识别。"
    return {"success": True, "vision_used": vision_used, "processed": processed_count, "manifest": manifest, "message": msg}

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
def update_step5_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 保存手动编辑修改的 reveal_manifest
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    # 人工保存后，校验并构建切层 assets，运行 build_reveal_scene.py
    build_scene_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_reveal_scene.py"))
    build_res = subprocess.run([
        sys.executable, build_scene_script, "--manifest", manifest_path
    ], capture_output=True, text=True, encoding="utf-8")
    
    if build_res.returncode != 0:
        logger.error(f"Build reveal scene failed: {build_res.stderr}")
        raise HTTPException(status_code=500, detail=f"构建切层素材失败: {build_res.stderr}")
        
    handle_step_navigation(project, 5, db)
    return {"success": True}

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
    
    # 动态将 setting 中的 TTS 参数写入环境变量，以便 minimax_tts.py 读取
    os.environ["MINIMAX_API_KEY"] = tts_api_key
    os.environ["MINIMAX_API_URL"] = get_setting("tts_endpoint", "https://api.minimaxi.com/v1/t2a_v2")
    os.environ["MINIMAX_MODEL"] = get_setting("tts_model", "speech-2.8-hd")
    os.environ["MINIMAX_VOICE_ID"] = get_setting("tts_voice_id", "Chinese (Mandarin)_Soft_Girl")
    os.environ["MINIMAX_SPEED"] = get_setting("tts_speed", "1.0")
    os.environ["MINIMAX_VOLUME"] = get_setting("tts_volume", "1.0")
    os.environ["MINIMAX_PITCH"] = get_setting("tts_pitch", "0")
        
    tts_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "minimax_tts.py"))
    
    # 循环对每一页 slide 分别生成音频
    for slide_id in slide_ids:
        text_file = os.path.join(project.run_dir, "slides", slide_id, "tts_text.txt")
        out_audio = os.path.join(project.run_dir, "slides", slide_id, "voice.mp3")
        out_meta = os.path.join(project.run_dir, "slides", slide_id, "tts_metadata.json")
        out_srt = os.path.join(project.run_dir, "slides", slide_id, "tts_narration.srt")
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
                
        with open(text_file, "r", encoding="utf-8") as f:
            tts_text = f.read().strip()
            
        logger.info(f"Synthesizing TTS audio for slide: {slide_id}")
        tts_args = [
            sys.executable, tts_script,
            "--text-file", text_file,
            "--out-audio", out_audio,
            "--out-meta", out_meta,
            "--out-srt", out_srt,
            "--out-timeline", out_timeline,
            "--slide-id", slide_id
        ]
        
        tts_res = subprocess.run(tts_args, capture_output=True, text=True, encoding="utf-8")
        if tts_res.returncode != 0:
            logger.error(f"TTS Synthesis failed for {slide_id}: {tts_res.stderr}")
            raise HTTPException(status_code=500, detail=f"语音合成失败: {tts_res.stderr}")
            
    # 合成完毕后，运行 bind_reveal_timeline.py 绑定时间轴
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run([
        sys.executable, bind_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")
        
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
        
    # 首先调用 build_remotion_props.py 生成渲染配置属性
    build_props_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_remotion_props.py"))
    props_res = subprocess.run([
        sys.executable, build_props_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if props_res.returncode != 0:
        logger.error(f"Build remotion props failed: {props_res.stderr}")
        raise HTTPException(status_code=500, detail=f"构建 Remotion 配置失败: {props_res.stderr}")
        
    # 接着，执行 Remotion 渲染
    # 检测 Node.js 模块依赖，执行 npm install (如果 node_modules 不存在)
    remotion_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "remotion"))
    node_modules_dir = os.path.join(remotion_dir, "node_modules")
    
    if not os.path.exists(node_modules_dir):
        logger.info("Initializing Remotion node_modules, running npm install...")
        # Windows 环境下运行 npm.cmd
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        npm_install = subprocess.run(
            [npm_cmd, "install"], cwd=remotion_dir, capture_output=True, text=True
        )
        if npm_install.returncode != 0:
            logger.error(f"npm install failed:\n{npm_install.stderr}")
            raise HTTPException(status_code=500, detail=f"初始化 Remotion Node 依赖失败: {npm_install.stderr}")
            
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
        npx_cmd, "remotion", "render", "ArticleVideo", output_mp4_path,
        f"--props={props_json_path}"
    ]
    
    render_res = subprocess.run(
        render_args, cwd=remotion_dir, capture_output=True, text=True
    )
    
    if render_res.returncode != 0:
        logger.error(f"Remotion render failed: {render_res.stderr}")
        raise HTTPException(status_code=500, detail=f"视频渲染失败: {render_res.stderr}")
        
    handle_step_navigation(project, 8, db)
    return {"success": True, "video_url": f"/api/projects/{project_id}/video"}

# 获取最终生成的 MP4 视频
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
