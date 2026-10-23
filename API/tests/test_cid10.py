def test_cid10_requires_authentication(client):
    response = client.get("/api/cid10?q=colera")

    assert response.status_code == 401


def test_cid10_searches_descriptions_without_accent_sensitivity(auth_client):
    response = auth_client.get("/api/cid10?q=colera")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["count"] > 0
    assert any(result["code"] == "A00" for result in payload["results"])
    assert any("Cólera" in result["description"] for result in payload["results"])


def test_cid10_searches_codes_with_or_without_punctuation(auth_client):
    response = auth_client.get("/api/cid10?q=A00.0")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["results"][0]["code"] == "A00.0"
    assert "Vibrio cholerae 01" in payload["results"][0]["description"]

    response_without_punctuation = auth_client.get("/api/cid10?q=A000")
    assert response_without_punctuation.status_code == 200
    assert response_without_punctuation.get_json()["results"][0]["code"] == "A00.0"


def test_cid10_rejects_empty_query(auth_client):
    response = auth_client.get("/api/cid10?q=%20")

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_cid10_limits_result_count(auth_client):
    response = auth_client.get("/api/cid10?q=a&limit=3")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 3
    assert len(payload["results"]) == 3


def test_cid10_openapi_documents_search_contract(auth_client):
    response = auth_client.get("/api/openapi.json")

    assert response.status_code == 200
    assert "/api/cid10" in response.get_json()["paths"]
