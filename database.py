import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'projects.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    current_step = Column(Integer, default=1)
    status = Column(String, default="active") # active, completed
    # step_status 存储 JSON 格式字符串，例如: 
    # {"1": "completed", "2": "pending_reconfirmation", "3": "pending"}
    step_status = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    run_dir = Column(String, nullable=False)

    def get_step_status(self):
        try:
            return json.loads(self.step_status) if self.step_status else {}
        except Exception:
            return {}

    def set_step_status(self, status_dict):
        self.step_status = json.dumps(status_dict)

class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=False)

# 初始化数据库结构
def init_db():
    Base.metadata.create_all(bind=engine)
    # 初始化默认设置
    db = SessionLocal()
    try:
        default_settings = {
            # LLM + Vision (共享)
            "llm_provider": "openai",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "",
            "llm_model": "gpt-4o-mini",
            "llm_temperature": "0.7",
            "llm_max_tokens": "16000",
            "vision_model": "gpt-4o",
            # Image Gen (独立)
            "image_base_url": "https://api.openai.com/v1",
            "image_api_key": "",
            "image_model": "gpt-image-1",
            "image_size": "1024x1024",
            # MiniMax TTS
            "tts_endpoint": "https://api.minimaxi.com/v1/t2a_async_v2",
            "tts_api_key": "",
            "tts_model": "speech-2.8-hd",
            "tts_voice_id": "Chinese (Mandarin)_Soft_Girl",
            "tts_speed": "1.0",
            "tts_volume": "1.0",
            "tts_pitch": "0"
        }
        for k, v in default_settings.items():
            existing = db.query(Setting).filter(Setting.key == k).first()
            if not existing:
                db.add(Setting(key=k, value=str(v)))
        db.commit()
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
