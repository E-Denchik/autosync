from flask import Blueprint, jsonify, request

from app.auth import admin_required, get_current_user, issue_token, login_required
from app.extensions import db
from app.models import User, UserRole

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
    """Создаёт первого администратора. Работает только пока в системе
    вообще нет пользователей — после этого эндпоинт навсегда недоступен,
    новых пользователей заводит уже admin_required /users."""
    if User.query.count() > 0:
        return jsonify(error="Настройка уже выполнена"), 403

    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify(error="'email' и 'password' обязательны"), 400
    if len(password) < 8:
        return jsonify(error="Пароль должен быть не короче 8 символов"), 400

    user = User(email=email, role=UserRole.ADMIN)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify(token=issue_token(user), user=_serialize_user(user)), 201


@bp.post("/login")
def login():
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.is_active or not user.check_password(password):
        return jsonify(error="Неверный email или пароль"), 401

    return jsonify(token=issue_token(user), user=_serialize_user(user))


@bp.get("/me")
@login_required
def me():
    return jsonify(_serialize_user(get_current_user()))


@bp.patch("/me/password")
@login_required
def change_own_password():
    """Пользователь меняет свой пароль сам — нужно знать текущий. До этого
    эндпоинта сменить пароль после первоначальной выдачи было вообще
    невозможно (только полное удаление и создание учётки заново)."""
    user = get_current_user()
    body = request.get_json(force=True) or {}
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if not user.check_password(current_password):
        return jsonify(error="Текущий пароль неверен"), 401
    if len(new_password) < 8:
        return jsonify(error="Новый пароль должен быть не короче 8 символов"), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify(_serialize_user(user))


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
    password = body.get("password") or ""
    role = body.get("role", UserRole.OPERATOR.value)

    if not email or not password:
        return jsonify(error="'email' и 'password' обязательны"), 400
    if len(password) < 8:
        return jsonify(error="Пароль должен быть не короче 8 символов"), 400
    if role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
        return jsonify(error="Недопустимая роль"), 400
    if User.query.filter_by(email=email).first():
        return jsonify(error="Пользователь с таким email уже существует"), 409

    user = User(email=email, role=UserRole(role))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(_serialize_user(user)), 201


@bp.patch("/users/<int:user_id>/password")
@admin_required
def admin_reset_password(user_id: int):
    """Администратор задаёт новый пароль другому пользователю напрямую, без
    знания старого — единственный способ восстановить доступ, если человек
    свой пароль забыл (публичного flow сброса по email в системе нет)."""
    user = db.get_or_404(User, user_id)
    body = request.get_json(force=True) or {}
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify(error="Пароль должен быть не короче 8 символов"), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify(_serialize_user(user))


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

    db.session.delete(user)
    db.session.commit()
    return "", 204
