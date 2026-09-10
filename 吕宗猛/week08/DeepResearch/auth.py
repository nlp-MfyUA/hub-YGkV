"""认证：JWT 签发/校验、bcrypt 密码、种子 admin。"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

import db

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
ACCESS_DAYS = 7


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_user(username: str, password: str) -> int:
    return db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, hash_password(password)),
    )


def get_user(username: str):
    return db.query_one("SELECT * FROM users WHERE username = ?", (username,))


def seed_admin():
    admin = db.query_one("SELECT * FROM users WHERE username = 'admin'")
    if not admin:
        create_user("admin", "admin123")


def issue_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"uid": user_id, "username": username, "iat": now, "exp": now + timedelta(days=ACCESS_DAYS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
