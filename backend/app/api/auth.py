from flask import Blueprint, jsonify, request

from app.auth import admin_required, get_current_user, issue_token, login_required
from app.extensions import db
from app.models import User, UserRole
from app.services.history import log_change

bp = Blueprint("auth", __name__)


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


@bp.get("/setup-required")
def setup_required():
    """Публичный, не требует токена — фронт вызывает его до логина, чтобы
    решить, показывать форму логина или мастер первого запуска (актуально
    для native-режима: там нет CLI, первого администратора заводят в
    браузере, см. Setup.jsx)."""
    return jsonify(setup_required=User.query.count() == 0)


@bp.post("/setup")
def setup():
    if User.query.count() > 0:
        return jsonify(error="Настройка уже выполнена"), 403

    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()

    if not email:
        return jsonify(error="'email' обязателен"), 400

    user = User(email=email, role=UserRole.ADMIN)
    db.session.add(user)
    db.session.flush()
    log_change("user", user.id, "created", actor=user, details={"email": email, "role": "admin", "via": "setup"})
    db.session.commit()

    return jsonify(token=issue_token(user), user=_serialize_user(user)), 201


@bp.get("/login-options")
def login_options():
    users = User.query.filter_by(is_active=True).order_by(User.email).all()
    return jsonify([_serialize_user(u) for u in users])


@bp.post("/login")
def login():
    body = request.get_json(force=True) or {}
    user_id = body.get("user_id")

    user = db.session.get(User, user_id) if user_id is not None else None
    if not user or not user.is_active:
        return jsonify(error="Пользователь не найден"), 401

    return jsonify(token=issue_token(user), user=_serialize_user(user))


@bp.get("/me")
@login_required
def me():
    return jsonify(_serialize_user(get_current_user()))


@bp.get("/users")
@admin_required
def list_users():
    users = User.query.order_by(User.created_at).all()
    return jsonify([_serialize_user(u) for u in users])


@bp.post("/users")
@admin_required
def create_user():
    """Создание новых пользователей — только администратором из UI,
    без публичной саморегистрации (внутренняя платформа)."""
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    role = body.get("role", UserRole.OPERATOR.value)

    if not email:
        return jsonify(error="'email' обязателен"), 400
    if role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
        return jsonify(error="Недопустимая роль"), 400
    if User.query.filter_by(email=email).first():
        return jsonify(error="Пользователь с таким email уже существует"), 409

    user = User(email=email, role=UserRole(role))
    db.session.add(user)
    db.session.flush()
    log_change(
        "user", user.id, "created", actor=get_current_user(), details={"email": email, "role": role}
    )
    db.session.commit()
    return jsonify(_serialize_user(user)), 201


@bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id: int):
    """Удаляет пользователя — доступ отзывается немедленно: и новый логин,
    и уже выданный JWT-токен, поскольку get_current_user() каждый раз
    проверяет, что пользователь ещё существует в БД (см. app/auth.py)."""
    current = get_current_user()
    if user_id == current.id:
        return jsonify(error="Нельзя удалить самого себя"), 400

    user = db.get_or_404(User, user_id)

    if user.role == UserRole.ADMIN:
        other_admins = User.query.filter(User.role == UserRole.ADMIN, User.id != user.id).count()
        if other_admins == 0:
            return jsonify(error="Нельзя удалить последнего администратора"), 400

    log_change(
        "user", user.id, "deleted", actor=current, details={"email": user.email, "role": user.role.value}
    )
    db.session.delete(user)
    db.session.commit()
    return "", 204
