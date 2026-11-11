"""B42: tabela CID-10 embarcada e busca por texto ou codigo (< 100 ms)."""
import time

import pytest

from backend.soap import cid10


def _codigos(resposta):
    return [r["code"] for r in resposta.get_json()["results"]]


# ---------- rota ----------

def test_cid10_requires_authentication(client):
    assert client.get("/api/cid10?q=colera").status_code == 401


def test_cid10_searches_descriptions_without_accent_sensitivity(auth_client):
    response = auth_client.get("/api/cid10?q=colera")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["query"] == "colera"
    assert payload["count"] == len(payload["results"]) > 0
    assert payload["results"][0] == {"code": "A00", "description": "Cólera"}


def test_cid10_searches_codes_with_or_without_punctuation(auth_client):
    for consulta in ("A00.0", "A000", "a00.0"):
        resultados = auth_client.get(f"/api/cid10?q={consulta}").get_json()["results"]
        assert resultados[0]["code"] == "A00.0"
        assert "Vibrio cholerae 01" in resultados[0]["description"]


def test_cid10_codigo_casa_pelo_inicio_com_o_exato_primeiro(auth_client):
    codigos = _codigos(auth_client.get("/api/cid10?q=J11&limit=10"))
    assert codigos[0] == "J11"
    assert set(codigos[1:]) <= {"J11.0", "J11.1", "J11.8"}
    # "00" nao e o inicio de nenhum codigo: nao lista A00, B00... pelo codigo
    assert "A00" not in _codigos(auth_client.get("/api/cid10?q=00&limit=100"))


def test_cid10_palavras_em_qualquer_ordem(auth_client):
    codigos = _codigos(auth_client.get("/api/cid10?q=tifoide%20febre"))
    assert "A01.0" in codigos  # Febre tifoide


def test_cid10_descricao_que_comeca_pelo_texto_vem_antes(auth_client):
    resultados = auth_client.get("/api/cid10?q=dengue&limit=5").get_json()["results"]
    assert resultados[0]["code"] == "A90"  # "Dengue [dengue clássico]"


@pytest.mark.parametrize("consulta", ["%20", "", "."])
def test_cid10_rejects_empty_query(auth_client, consulta):
    response = auth_client.get(f"/api/cid10?q={consulta}")
    if consulta == ".":
        # So pontuacao: nada para buscar, mas nao e erro do cliente
        assert response.status_code == 200 and response.get_json()["count"] == 0
    else:
        assert response.status_code == 400
        assert response.get_json()["status"] == "error"


def test_cid10_limits_result_count(auth_client):
    payload = auth_client.get("/api/cid10?q=a&limit=3").get_json()
    assert payload["count"] == 3
    assert len(payload["results"]) == 3


@pytest.mark.parametrize("limite", ["0", "101", "x"])
def test_cid10_limite_invalido(auth_client, limite):
    assert auth_client.get(f"/api/cid10?q=a&limit={limite}").status_code == 400


def test_cid10_openapi_documents_search_contract(client):
    spec = client.get("/api/openapi.json").get_json()
    assert spec["paths"]["/api/cid10"]["get"]["operationId"] == "searchCid10"
    assert "Cid10BuscaResposta" in spec["components"]["schemas"]


# ---------- tabela ----------

def test_tabela_tem_categorias_e_subcategorias_em_portugues():
    catalogo = cid10._load_catalog()
    codigos = {item.code for item in catalogo}
    assert len(catalogo) > 14_000
    assert {"A00", "A00.0", "J11", "J11.1"} <= codigos
    assert all(item.description for item in catalogo)
    # A90 (sem subdivisao) esta nos dois CSVs: sai uma vez so
    assert len(codigos) == len(catalogo)
    assert _codigos_da_busca("dengue").count("A90") == 1


def _codigos_da_busca(texto):
    return [item["code"] for item in cid10.search(texto, limit=50)]


def test_codigos_da_tabela_passam_no_validador_do_soap():
    # O SoapEditor grava o codigo escolhido aqui; o SoapV1 (B39) tem de aceita-lo.
    from backend.soap import validar_soap

    base = {"subjetivo": "s", "objetivo": "o", "avaliacao": "a", "plano": "p"}
    for item in cid10.search("gripe", limit=10):
        soap = validar_soap({**base, "hipoteses": [
            {"descricao": "Hipótese", "cid10": item["code"], "confianca": "media"}]})
        assert soap.hipoteses[0].cid10 == item["code"]


@pytest.mark.parametrize("consulta", ["a", "dengue", "J11", "febre tifoide", "dor abdominal", "xyzxyz"])
def test_busca_abaixo_de_100_ms(consulta):
    cid10.preload()
    inicio = time.perf_counter()
    cid10.search(consulta, limit=20)
    assert time.perf_counter() - inicio < 0.1
