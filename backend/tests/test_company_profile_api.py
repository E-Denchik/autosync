def test_get_profile_defaults_to_empty(client, operator_headers):
    resp = client.get("/api/company-profile", headers=operator_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "COMPANY_NAME": "",
        "COMPANY_INN": "",
        "COMPANY_ADDRESS": "",
        "COMPANY_PHONE": "",
    }


def test_update_profile_persists_values(client, admin_headers):
    resp = client.put(
        "/api/company-profile",
        headers=admin_headers,
        json={"COMPANY_NAME": "ИП Иванов", "COMPANY_INN": "123456789"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["COMPANY_NAME"] == "ИП Иванов"
    assert body["COMPANY_INN"] == "123456789"

    resp2 = client.get("/api/company-profile", headers=admin_headers)
    assert resp2.get_json()["COMPANY_NAME"] == "ИП Иванов"
