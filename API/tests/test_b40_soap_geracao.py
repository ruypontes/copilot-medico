"""B40 - prompt SOAP em PT-BR com response_schema, 1 retry e rota de geracao."""
import json
import re

import pytest
from sqlalchemy import text

from backend.soap import gerador, response_schema, validar_soap
from backend.soap.material import montar_material
from ids import DOCTOR_B, TEST_USER_ID
from repositories import (
    ConsultaRepository,
    DadoExtensaoRepository,
    MensagemRepository,
    PacienteRepository,
    TranscricaoRepository,
    sessao,
)


def _soap(**extra):
    base = {
        "subjetivo": "Cefaleia em aperto ha 3 dias.",
        "objetivo": "PA 120/80 mmHg; SatO2 98%.",
        "avaliacao": "Provavel cefaleia tensional.",
        "plano": "Dipirona 1 g se dor; retorno em 7 dias.",
        "hipoteses": [{"descricao": "Cefaleia tensional", "cid10": "G44.2", "confianca": "alta"}],
        "alertas": [],
        "pendencias": ["Fundoscopia nao realizada"],
    }
    base.update(extra)
    return base


class ModeloFalso:
    """Devolve as respostas na ordem e guarda o que recebeu."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, instrucao, conteudo, schema=None):
        self.chamadas.append({"instrucao": instrucao, "conteudo": conteudo, "schema": schema})
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if isinstance(resposta, str) else json.dumps(resposta)


# --- prompt ---------------------------------------------------------------------

def test_prompt_versionado_em_arquivo_e_em_ptbr():
    assert gerador.PROMPT_ID == "soap" and gerador.PROMPT_VERSAO == "1"
    assert "português do Brasil" in gerador.INSTRUCAO
    for secao in ("subjetivo", "objetivo", "avaliacao", "plano", "hipoteses", "alertas", "pendencias"):
        assert secao in gerador.INSTRUCAO


def test_prompt_proibe_referencias_e_percentuais():
    instrucao = gerador.INSTRUCAO
    assert "Nunca cite referências" in instrucao
    assert "Não use percentuais" in instrucao
    assert '"baixa", "media" ou "alta"' in instrucao
    # D-07: o prompt antigo pedia PubMed/links e probabilidade em %.
    assert "PubMed" not in instrucao and "http" not in instrucao


# --- regras de conteudo -------------------------------------------------------------

@pytest.mark.parametrize("campos, esperado", [
    ({}, []),
    ({"objetivo": "SatO2 96%, FR 18 irpm."}, []),  # medida clinica com % e permitida
    ({"avaliacao": "Provavel IVAS; SatO2 96%."}, []),
    ({"avaliacao": "Pneumonia com 80% de probabilidade."}, ["avaliacao"]),
    ({"avaliacao": "Chance de 30% de IAM."}, ["avaliacao"]),
    ({"plano": "Ver https://pubmed.ncbi.nlm.nih.gov/123"}, ["plano"]),
    ({"avaliacao": "Conforme Smith et al. (2020)."}, ["avaliacao"]),
    ({"alertas": ["Ver doi: 10.1000/xyz"]}, ["alertas.0"]),
    ({"hipoteses": [{"descricao": "IVAS 90%", "confianca": "alta"}]}, ["hipoteses.0.descricao"]),
])
def test_verificar_conteudo(campos, esperado):
    erros = gerador.verificar_conteudo(validar_soap(_soap(**campos)))

    assert [e.split(":")[0] for e in erros] == esperado


# --- geracao com 1 retry ------------------------------------------------------------

def test_valido_na_primeira_tentativa():
    modelo = ModeloFalso(_soap())

    resultado = gerador.gerar_soap("## Transcrição\nMédico: ...", modelo)

    assert resultado.tentativas == 1 and resultado.soap.avaliacao == "Provavel cefaleia tensional."
    assert modelo.chamadas[0]["instrucao"] == gerador.INSTRUCAO
    assert modelo.chamadas[0]["schema"] == response_schema()


@pytest.mark.parametrize("primeira", [
    "isto nao e json",
    {"subjetivo": "so isso"},
    _soap(hipoteses=[{"descricao": "Cefaleia", "confianca": "90%"}]),
    _soap(plano="Ver https://exemplo.org"),
])
def test_um_retry_com_os_erros_da_primeira(primeira):
    modelo = ModeloFalso(primeira, _soap())

    resultado = gerador.gerar_soap("MATERIAL", modelo)

    assert resultado.tentativas == 2
    segundo = modelo.chamadas[1]["conteudo"]
    assert segundo.startswith("MATERIAL") and "foi rejeitada" in segundo


def test_invalido_duas_vezes_desiste_sem_terceira_chamada():
    modelo = ModeloFalso("nao e json", {"subjetivo": "x"}, _soap())

    with pytest.raises(gerador.SoapNaoGerado) as erro:
        gerador.gerar_soap("MATERIAL", modelo)

    assert len(modelo.chamadas) == 2  # a primeira + 1 retry, nunca mais
    assert erro.value.tentativas == 2 and any("plano" in e for e in erro.value.erros)


def test_erro_do_modelo_sobe_sem_retry():
    modelo = ModeloFalso(RuntimeError("cota"), _soap())

    with pytest.raises(RuntimeError):
        gerador.gerar_soap("MATERIAL", modelo)
    assert len(modelo.chamadas) == 1


def test_material_vazio():
    with pytest.raises(ValueError):
        gerador.gerar_soap("   ", ModeloFalso(_soap()))


# --- material da consulta ------------------------------------------------------------

def test_material_junta_as_fontes_e_ignora_respostas_da_ia():
    material = montar_material(
        transcricoes=[{"dialogue": [{"role": "Médico", "text": "O que sente?"}, {"role": "Paciente", "text": "Dor"}]}],
        dados_extensao=[
            {"content": [{"role": "peso", "text": "70"}]},
            {"content": {"queixa": ["dor", "febre"], "pa": "120/80"}},
            {"content": "Texto corrido do prontuario"},
        ],
        mensagens=[
            {"role": "user", "parts": [{"text": "Texto extraido do PDF: hemograma normal"}]},
            {"role": "model", "parts": [{"text": "Resposta da IA que nao deve entrar"}]},
        ],
    )

    assert "## Transcrição da consulta\nMédico: O que sente?\nPaciente: Dor" in material
    assert "peso: 70" in material and "queixa: dor, febre" in material and "Texto corrido do prontuario" in material
    assert "hemograma normal" in material
    assert "Resposta da IA" not in material


def test_material_vazio_quando_nao_ha_nada():
    assert montar_material([], [], [{"role": "model", "parts": [{"text": "so IA"}]}]) == ""


# --- rota POST /api/consultations/<id>/soap -------------------------------------------

@pytest.fixture()
def cofre(monkeypatch):
    """Medico logado com o cofre aberto (B26): so assim o mapa de
    anonimizacao da consulta e persistido e o GET consegue reidratar."""
    import server
    from backend.anonimizacao.cripto import criar_cofre

    aberto = criar_cofre("senha-de-teste")[0]
    monkeypatch.setattr(server, "_cofre_atual", lambda: aberto)
    return aberto


@pytest.fixture()
def consulta(client, cofre):
    s = sessao.obter_sessao()
    pid = PacienteRepository(s).criar(nome="Maria Souza", medico_id=TEST_USER_ID)["id"]
    return pid, ConsultaRepository(s).criar(pid, "Consulta")


@pytest.fixture()
def modelo(monkeypatch):
    import server

    falso = ModeloFalso()
    monkeypatch.setattr(server.gemini_connection, "gerar_resposta_unica", falso)
    return falso


def _transcrever(pid, cid, texto):
    TranscricaoRepository(sessao.obter_sessao()).adicionar(pid, cid, texto=texto, duracao_s=60)


def _token(conteudo):
    return re.search(r"\[[A-Z]+(?:_\d+)?\]", conteudo).group(0)


def test_gera_grava_tokenizado_e_devolve_reidratado(client, auth_headers, consulta, monkeypatch):
    import server

    pid, cid = consulta
    _transcrever(pid, cid, "Maria Souza relata cefaleia ha 3 dias.")
    chamadas = []

    def responde(instrucao, conteudo, schema=None):
        # Ecoa o token que o modelo recebeu no lugar do nome.
        chamadas.append({"conteudo": conteudo, "schema": schema})
        return json.dumps(_soap(subjetivo=f"{_token(conteudo)} relata cefaleia ha 3 dias."))

    monkeypatch.setattr(server.gemini_connection, "gerar_resposta_unica", responde)

    r = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))

    body = r.get_json()
    assert r.status_code == 201 and body["tentativas"] == 1
    assert "Maria Souza" not in chamadas[0]["conteudo"]
    assert chamadas[0]["schema"] == response_schema()
    assert body["soap"]["versao_ia"]["subjetivo"] == "Maria Souza relata cefaleia ha 3 dias."
    assert body["soap"]["prompt"] == {"id": "soap", "versao": "1"}
    gravado = sessao.obter_sessao().execute(text("select versao_ia from documento_soap")).scalar_one()
    gravado = gravado if isinstance(gravado, dict) else json.loads(gravado)
    assert "Maria" not in gravado["subjetivo"] and gravado["subjetivo"].startswith("[")

    # GET do B44 tambem devolve reidratado.
    r = client.get(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))
    assert r.get_json()["soap"]["versao_ia"]["subjetivo"].startswith("Maria Souza")


def test_edicao_do_medico_volta_a_ser_tokenizada(client, auth_headers, consulta, monkeypatch):
    import server

    pid, cid = consulta
    _transcrever(pid, cid, "Maria Souza relata cefaleia.")
    monkeypatch.setattr(server.gemini_connection, "gerar_resposta_unica",
                        lambda i, c, s=None: json.dumps(_soap(subjetivo=f"{_token(c)} relata cefaleia.")))
    soap = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico")).get_json()["soap"]

    editado = {**soap["atual"], "plano": "Maria Souza deve retornar em 7 dias."}
    r = client.put(f"/api/consultations/{cid}/soap/{soap['id']}", json={"versao_medico": editado},
                   headers=auth_headers("medico"))

    assert r.status_code == 200
    assert r.get_json()["soap"]["versao_medico"]["plano"] == "Maria Souza deve retornar em 7 dias."
    gravado = sessao.obter_sessao().execute(text("select versao_medico from documento_soap")).scalar_one()
    gravado = gravado if isinstance(gravado, dict) else json.loads(gravado)
    assert "Maria" not in json.dumps(gravado, ensure_ascii=False)


def test_material_vem_das_tres_fontes_da_propria_consulta(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    s = sessao.obter_sessao()
    outra = ConsultaRepository(s).criar(pid, "Outra")
    _transcrever(pid, cid, "Paciente com tosse.")
    _transcrever(pid, outra, "De outra consulta.")
    DadoExtensaoRepository(s).adicionar(pid, {"pa": "130/85"}, consulta_id=cid)
    MensagemRepository(s).adicionar(cid, "user", "Anotacao do medico.")
    MensagemRepository(s).adicionar(cid, "model", "Resposta da IA.")
    modelo.respostas.append(_soap())

    assert client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico")).status_code == 201

    enviado = modelo.chamadas[0]["conteudo"]
    assert "Paciente com tosse." in enviado and "pa: 130/85" in enviado and "Anotacao do medico." in enviado
    assert "De outra consulta." not in enviado and "Resposta da IA." not in enviado


def test_sem_material_400_sem_chamar_o_modelo(client, auth_headers, consulta, modelo):
    _pid, cid = consulta

    r = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))

    assert r.status_code == 400 and modelo.chamadas == []


def test_invalido_duas_vezes_502_e_nada_gravado(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcrever(pid, cid, "Paciente com tosse.")
    modelo.respostas += ["nao e json", {"subjetivo": "x"}]

    r = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))

    assert r.status_code == 502 and r.get_json()["errors"]
    assert len(modelo.chamadas) == 2
    assert sessao.obter_sessao().execute(text("select count(*) from documento_soap")).scalar_one() == 0


def test_retry_que_funciona_grava_o_soap(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcrever(pid, cid, "Paciente com tosse.")
    modelo.respostas += ["nao e json", _soap()]

    r = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))

    assert r.status_code == 201 and r.get_json()["tentativas"] == 2


def test_cota_esgotada_vira_429(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcrever(pid, cid, "Paciente com tosse.")

    class ResourceExhausted(Exception):
        pass

    modelo.respostas.append(ResourceExhausted("quota"))
    r = client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico"))

    assert r.status_code == 429 and "Limite de uso" in r.get_json()["message"]


def test_outra_falha_do_modelo_vira_502(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcrever(pid, cid, "Paciente com tosse.")
    modelo.respostas.append(RuntimeError("rede"))

    assert client.post(f"/api/consultations/{cid}/soap", headers=auth_headers("medico")).status_code == 502


def test_outro_medico_403_e_sem_token_401(client, consulta, monkeypatch):
    from backend import auth_decorators

    _pid, cid = consulta
    assert client.post(f"/api/consultations/{cid}/soap").status_code == 401
    monkeypatch.setattr(auth_decorators, "get_user_from_token", lambda _t: (
        {"id": DOCTOR_B, "email": "b@example.com", "name": "B", "profiles": ["medico"], "active": True},
        {"profile": "medico"},
    ))
    r = client.post(f"/api/consultations/{cid}/soap", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403
