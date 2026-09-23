import os
from app.db import Base, engine, SessionLocal
from app.models import User
from app.security import hash_password
from app.migrations import run_lightweight_migrations
from app.services.reference_data import ensure_default_reference_data

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)
db = SessionLocal()
try:
    ensure_default_reference_data(db)
    if not db.query(User).first():
        username = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
        password = os.getenv("INITIAL_ADMIN_PASSWORD", "ChangeMe123!")
        full_name = os.getenv("INITIAL_ADMIN_NAME", "Администратор")
        db.add(User(username=username, full_name=full_name, password_hash=hash_password(password), role="admin", active=True))
        db.commit()
        print(f"Создан администратор: {username}. Смените пароль после первого входа.")
    else:
        print("Инициализация выполнена. Пользователи уже существуют.")
finally:
    db.close()
