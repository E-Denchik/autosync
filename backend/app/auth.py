"""JWT-авторизация. SPA-фронтенд шлёт токен в заголовке
Authorization: Bearer <token>, полученный от /api/auth/login.

Никакой сессии на сервере не хранится — токен самодостаточен и просто
проверяется на каждый запрос через декоратор login_required.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from app.models import User, UserRole


def issue_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "role": user.role.value,
        "exp": datetime.utcnow() + timedelta(hours=current_app.config["JWT_EXPIRES_HOURS"]),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_current_user() -> User | None:
    if "current_user" in g:
        return g.current_user

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        g.current_user = None
        return None

    payload = _decode_token(auth_header[len("Bearer ") :])
    if not payload:
        g.current_user = None
        return None

    user = User.query.get(payload.get("sub"))
    g.current_user = user if user and user.is_active else None
    return g.current_user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # CORS-preflight (OPTIONS) никогда не несёт Authorization — если его
        # тут заворачивать в 401, браузер сочтёт preflight проваленным и
        # заблокирует сам запрос ещё до того, как до нас дойдёт токен.
        # Пропускаем OPTIONS, чтобы flask-cors мог штатно на него ответить.
        if request.method == "OPTIONS":
            return fn(*args, **kwargs)
        if get_current_user() is None:
            return jsonify(error="Требуется авторизация"), 401
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return fn(*args, **kwargs)
        user = get_current_user()
        if user is None:
            return jsonify(error="Требуется авторизация"), 401
        if user.role != UserRole.ADMIN:
            return jsonify(error="Требуются права администратора"), 403
        return fn(*args, **kwargs)

    return wrapper
