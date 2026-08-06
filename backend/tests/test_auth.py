from app.extensions import db
from app.models import User, UserRole


def test_setup_required_true_when_no_users(client):
    resp = client.get("/api/auth/setup-required")
    assert resp.status_code == 200
    assert resp.get_json() == {"setup_required": True}


def test_setup_creates_first_admin_and_issues_token(client, app):
    resp = client.post(
        "/api/auth/setup", json={"email": "First@Company.ru", "password": "supersecret"}
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["email"] == "first@company.ru"  # normalized to lowercase
    assert body["user"]["role"] == "admin"
    assert "token" in body

    with app.app_context():
        assert User.query.count() == 1

    # повторный вызов после появления пользователя должен быть закрыт
    resp2 = client.post(
        "/api/auth/setup", json={"email": "second@company.ru", "password": "supersecret"}
    )
    assert resp2.status_code == 403


def test_setup_rejects_short_password(client):
    resp = client.post("/api/auth/setup", json={"email": "a@b.ru", "password": "short"})
    assert resp.status_code == 400


def test_login_success_and_failure(client, admin_headers):
    resp = client.post(
        "/api/auth/login", json={"email": "admin@test.local", "password": "adminpass123"}
    )
    assert resp.status_code == 200
    assert "token" in resp.get_json()

    resp_bad = client.post(
        "/api/auth/login", json={"email": "admin@test.local", "password": "wrong"}
    )
    assert resp_bad.status_code == 401


def test_endpoints_require_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    resp2 = client.get("/api/dashboard/summary")
    assert resp2.status_code == 401


def test_me_returns_current_user(client, admin_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "admin@test.local"


def test_operator_cannot_manage_users(client, operator_headers):
    resp = client.get("/api/auth/users", headers=operator_headers)
    assert resp.status_code == 403


def test_admin_can_create_list_and_delete_user(client, admin_headers, app):
    create_resp = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "new.op@test.local", "password": "operatorpass123", "role": "operator"},
    )
    assert create_resp.status_code == 201
    new_user_id = create_resp.get_json()["id"]

    list_resp = client.get("/api/auth/users", headers=admin_headers)
    emails = [u["email"] for u in list_resp.get_json()]
    assert "new.op@test.local" in emails

    delete_resp = client.delete(f"/api/auth/users/{new_user_id}", headers=admin_headers)
    assert delete_resp.status_code == 204

    with app.app_context():
        assert db.session.get(User, new_user_id) is None


def test_deleted_user_token_immediately_loses_access(client, admin_headers, app):
    create_resp = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "revoke.me@test.local", "password": "operatorpass123", "role": "operator"},
    )
    victim_headers = _login(client, "revoke.me@test.local", "operatorpass123")

    # токен рабочий, пока пользователь существует
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 200

    victim_id = create_resp.get_json()["id"]
    client.delete(f"/api/auth/users/{victim_id}", headers=admin_headers)

    # тот же самый (ещё не истёкший) токен должен сразу же перестать работать
    resp = client.get("/api/auth/me", headers=victim_headers)
    assert resp.status_code == 401


def test_cannot_delete_self(client, admin_headers, app):
    with app.app_context():
        admin_id = User.query.filter_by(email="admin@test.local").first().id
    resp = client.delete(f"/api/auth/users/{admin_id}", headers=admin_headers)
    assert resp.status_code == 400


def test_admin_can_delete_another_admin(client, admin_headers, app):
    with app.app_context():
        other = User(email="other-admin@test.local", role=UserRole.ADMIN)
        other.set_password("adminpass123")
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    resp = client.delete(f"/api/auth/users/{other_id}", headers=admin_headers)
    assert resp.status_code == 204


def test_change_own_password_requires_correct_current_password(client, admin_headers):
    resp = client.patch(
        "/api/auth/me/password",
        headers=admin_headers,
        json={"current_password": "wrong", "new_password": "newpassword123"},
    )
    assert resp.status_code == 401


def test_change_own_password_rejects_short_new_password(client, admin_headers):
    resp = client.patch(
        "/api/auth/me/password",
        headers=admin_headers,
        json={"current_password": "adminpass123", "new_password": "short"},
    )
    assert resp.status_code == 400


def test_change_own_password_success_and_old_password_stops_working(client, admin_headers):
    resp = client.patch(
        "/api/auth/me/password",
        headers=admin_headers,
        json={"current_password": "adminpass123", "new_password": "newpassword123"},
    )
    assert resp.status_code == 200

    old_login = client.post(
        "/api/auth/login", json={"email": "admin@test.local", "password": "adminpass123"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login", json={"email": "admin@test.local", "password": "newpassword123"}
    )
    assert new_login.status_code == 200


def test_change_own_password_requires_auth(client):
    resp = client.patch(
        "/api/auth/me/password", json={"current_password": "x", "new_password": "newpassword123"}
    )
    assert resp.status_code == 401


def test_admin_reset_password_for_another_user(client, admin_headers, app):
    create_resp = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"email": "forgetful@test.local", "password": "operatorpass123", "role": "operator"},
    )
    user_id = create_resp.get_json()["id"]

    reset_resp = client.patch(
        f"/api/auth/users/{user_id}/password",
        headers=admin_headers,
        json={"new_password": "brandnewpass123"},
    )
    assert reset_resp.status_code == 200

    login_resp = client.post(
        "/api/auth/login", json={"email": "forgetful@test.local", "password": "brandnewpass123"}
    )
    assert login_resp.status_code == 200


def test_operator_cannot_reset_others_password(client, operator_headers, admin_headers, app):
    with app.app_context():
        target_id = User.query.filter_by(email="admin@test.local").first().id
    resp = client.patch(
        f"/api/auth/users/{target_id}/password",
        headers=operator_headers,
        json={"new_password": "brandnewpass123"},
    )
    assert resp.status_code == 403


def _login(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}
