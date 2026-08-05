import os
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from database_migrations import run_migrations

logger = logging.getLogger("PPTStudio.Database")

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'projects.db')}"

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        # SQLite 默认 5 秒 busy timeout；渲染线程、one-click 线程与 HTTP
        # 请求并发写时会抛 "database is locked"。调大超时并开启 WAL 减少写锁冲突。
        "timeout": 30,
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utc_now_naive() -> datetime:
    """Return UTC in the naïve form used by the existing SQLite schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

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
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    run_dir = Column(String, nullable=False)
    # AI 模式：auto=自动调用 AI 做分镜规划/可视化/Mask；manual=手动填写，保留按需触发 AI
    ai_mode = Column(String, default="auto")

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


DEFAULT_SETTINGS = {
    # LLM + Vision (共享)
    "llm_provider": "openai",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_api_key": "",
    "llm_model": "gpt-4o-mini",
    "llm_temperature": "0.7",
    "llm_max_tokens": "50000",
    "vision_model": "gpt-4o",
    # Image Gen (独立)
    "image_base_url": "https://api.openai.com/v1",
    "image_api_key": "",
    "image_model": "gpt-image-1",
    "image_size": "1024x1024",
    # TTS
    "tts_provider": "minimax",
    "tts_endpoint": "https://api.minimaxi.com/v1/t2a_async_v2",
    "tts_api_key": "",
    "tts_secret_key": "",
    "tts_region": "",
    "tts_model": "speech-2.8-hd",
    "tts_voice_id": "Chinese (Mandarin)_Soft_Girl",
    "tts_clone_voice_id": "",
    "tts_provider_extra": "",
    "tts_speed": "1.2",
    "tts_volume": "1.0",
    "tts_pitch": "0",
}

LEGACY_DEFAULTS = {
    "llm_max_tokens": ("16000", "50000"),
    "tts_speed": ("1.0", "1.2"),
}


class ArtifactRecord(Base):
    __tablename__ = "artifact_records"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, nullable=False, index=True)
    artifact_type = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    relative_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    source_fingerprint = Column(Text, nullable=False, default="{}")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    def get_source_fingerprint(self):
        try:
            return json.loads(self.source_fingerprint) if self.source_fingerprint else {}
        except Exception:
            return {}

    def get_metadata(self):
        try:
            return json.loads(self.metadata_json) if self.metadata_json else {}
        except Exception:
            return {}


class LocalJob(Base):
    __tablename__ = "local_jobs"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, nullable=False, index=True)
    job_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String, nullable=False, default="queued")
    error = Column(Text, nullable=True)
    result_artifact_id = Column(String, nullable=True)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def get_payload(self):
        try:
            return json.loads(self.payload_json) if self.payload_json else {}
        except Exception:
            return {}

# 初始化数据库结构
def init_db():
    # 开启 WAL 模式，配合 busy timeout 减少多写线程冲突。
    # WAL 允许读与写并发，显著降低 "database is locked" 概率。
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA busy_timeout=30000")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
            connection.commit()
    except Exception:
        logger.error("Failed to enable SQLite WAL mode", exc_info=True)
    run_migrations(engine)
    # 初始化默认设置
    db = SessionLocal()
    try:
        # A query-then-insert loop races when multiple workers start together.
        # SQLite conflict handling makes seeding atomic while preserving
        # existing user-configured values.
        statement = sqlite_insert(Setting).values(
            [{"key": key, "value": str(value)} for key, value in DEFAULT_SETTINGS.items()]
        )
        db.execute(statement.on_conflict_do_nothing(index_elements=["key"]))

        for key, (old_value, new_value) in LEGACY_DEFAULTS.items():
            existing = db.query(Setting).filter(Setting.key == key).first()
            if existing and existing.value == old_value:
                existing.value = new_value
        db.commit()
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
