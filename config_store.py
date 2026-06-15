from database import SessionLocal, Setting

def get_setting(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        item = db.query(Setting).filter(Setting.key == key).first()
        return item.value if item else default
    finally:
        db.close()

def get_all_settings() -> dict:
    db = SessionLocal()
    try:
        items = db.query(Setting).all()
        return {item.key: item.value for item in items}
    finally:
        db.close()

def update_settings(settings_dict: dict):
    db = SessionLocal()
    try:
        for k, v in settings_dict.items():
            item = db.query(Setting).filter(Setting.key == k).first()
            if item:
                item.value = str(v)
            else:
                db.add(Setting(key=k, value=str(v)))
        db.commit()
    finally:
        db.close()
