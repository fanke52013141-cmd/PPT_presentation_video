from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database


def test_default_settings_initialization_is_concurrency_safe(tmp_path) -> None:
    original_engine = database.engine
    original_session_local = database.SessionLocal
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'projects.db'}",
        connect_args={"check_same_thread": False},
    )
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    database.engine = test_engine
    database.SessionLocal = test_session_local

    try:
        database.Base.metadata.create_all(bind=test_engine)
        with test_session_local() as db:
            db.add(database.Setting(key="llm_model", value="custom-model"))
            db.commit()

        worker_count = 8
        barrier = Barrier(worker_count)

        def initialize() -> None:
            barrier.wait()
            database.init_db()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(initialize) for _ in range(worker_count)]
            for future in futures:
                future.result()

        with test_session_local() as db:
            settings = {item.key: item.value for item in db.query(database.Setting).all()}

        assert len(settings) == len(database.DEFAULT_SETTINGS)
        assert settings["llm_model"] == "custom-model"
        assert settings["llm_max_tokens"] == "50000"
        assert settings["tts_speed"] == "1.2"
    finally:
        test_engine.dispose()
        database.engine = original_engine
        database.SessionLocal = original_session_local
