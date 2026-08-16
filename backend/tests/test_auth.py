from app.extensions import db
from app.models import User, UserRole


def test_setup_required_true_when_no_users(client):
    resp = client.get("/api/auth/setup-required")
    assert resp.status_code == 200
    assert resp.get_json() == {"setup_required": True}


def test_setup_creates_first_admin_and_issues_token(client, app):
    resp = client.post("/api/auth/setup", json={"email": "First@Company.ru"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["email"] == "first@company.ru"  # normalized to lowercase
    assert body["user"]["role"] == "admin"
    assert "token" in body

    with app.app_context():
        assert User.query.count() == 1

    # повторный вызов после появления пользователя должен быть закрыт
    resp2 = client.post("/api/auth/setup", json={"email": "second@company.ru"})
    assert resp2.status_code == 403


def test_setup_rejects_empty_email(client):
    resp = client.post("/api/auth/setup", json={"email": ""})
    assert resp.status_code == 400


def test_login_success_and_unknown_user(client, admin_headers, app):
    with app.app_context():
        admin_id = User.query.filter_by(email="admin@test.local").first().id

    resp = client.post("/api/auth/login", json={"user_id": admin_id})
    assert resp.status_code == 200
    assert "token" in resp.get_json()

    resp_bad = client.post("/api/auth/login", json={"user_id": 999999})
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
        json={"email": "new.op@test.local", "role": "operator"},
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
        json={"email": "revoke.me@test.local", "role": "operator"},
    )
    victim_id = create_resp.get_json()["id"]
    victim_headers = _login(client, victim_id)

    # токен рабочий, пока пользователь существует
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 200

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
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    resp = client.delete(f"/api/auth/users/{other_id}", headers=admin_headers)
    assert resp.status_code == 204


def _login(client, user_id):
    resp = client.post("/api/auth/login", json={"user_id": user_id})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}
