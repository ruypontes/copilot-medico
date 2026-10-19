"""B38 - recomendacoes sobre a janela parcial da consulta (US020)."""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from backend import recomendacoes as rec
from ids import DOCTOR_B, TEST_USER_ID
from models import Mensagem, Transcricao
from repositories import ConsultaRepository, PacienteRepository, TranscricaoRepository, sessao

URL = "/api/recommendations"


# --- regras do modulo -----------------------------------------------------------

@pytest.mark.parametrize("valor, esperado", [(None, 5), ("", 5), (2, 2), ("10", 10), (120, 120)])
def test_janela_valida(valor, esperado):
    assert rec.validar_janela(valor) == esperado


@pytest.mark.parametrize("valor", [0, -1, 121, "abc", True, 1.5])
def test_janela_invalida(valor):
    with pytest.raises(rec.JanelaInvalida):
        rec.validar_janela(valor)


def test_trecho_usa_turnos_com_papel_e_cai_no_texto_sem_turnos():
    trecho = rec.montar_trecho([
        {"dialogue": [{"role": "Médico", "text": "O que sente?"}, {"role": "Paciente", "text": "Dor"}]},
        {"dialogue": None, "text": "Texto corrido sem diarizacao"},
        {"dialogue": [], "text": "  "},
    ])

    assert trecho == "Médico: O que sente?\nPaciente: Dor\n\nTexto corrido sem diarizacao"


def test_resposta_json_limitada_a_cinco_itens():
    bruta = json.dumps({"itens": [{"tipo": "exame", "texto": f"Item {i}"} for i in range(8)]})

    itens = rec.interpretar_resposta(bruta)

    assert len(itens) == rec.MAX_ITENS
    assert itens[0] == {"tipo": "exame", "texto": "Item 0"}


def test_item_longo_e_cortado_em_vinte_palavras():
    longo = " ".join(f"palavra{i}" for i in range(30))

    texto = rec.interpretar_resposta(json.dumps({"itens": [{"tipo": "alerta", "texto": longo}]}))[0]["texto"]

    assert len(texto.rstrip("…").split()) == rec.MAX_PALAVRAS
    assert texto.endswith("…")


def test_json_em_cerca_de_codigo_e_tipo_desconhecido():
    bruta = '```json\n{"itens": [{"tipo": "conduta", "texto": "Reavaliar em 48h"}]}\n```'

    assert rec.interpretar_resposta(bruta) == [{"tipo": "outro", "texto": "Reavaliar em 48h"}]


def test_sem_json_aproveita_lista_e_ignora_o_resto():
    bruta = "Sugestões:\n- Perguntar sobre febre\n2. Medir pressão arterial\nObrigado."

    assert [i["texto"] for i in rec.interpretar_resposta(bruta)] == [
        "Perguntar sobre febre", "Medir pressão arterial",
    ]


@pytest.mark.parametrize("bruta", ["", "nada util", '{"itens": "x"}', '{"itens": [{"texto": ""}]}'])
def test_resposta_sem_itens(bruta):
    assert rec.interpretar_resposta(bruta) == []


def test_prompt_versionado_respeita_os_limites():
    assert rec.PROMPT_ID and rec.PROMPT_VERSAO
    assert f"MÁXIMO {rec.MAX_ITENS} itens" in rec.INSTRUCAO
    assert f"{rec.MAX_PALAVRAS} palavras" in rec.INSTRUCAO
    assert "Nunca feche um diagnóstico" in rec.INSTRUCAO


# --- rota -----------------------------------------------------------------------

@pytest.fixture()
def consulta(client):
    s = sessao.obter_sessao()
    pid = PacienteRepository(s).criar(nome="Maria Souza", medico_id=TEST_USER_ID)["id"]
    cid = ConsultaRepository(s).criar(pid, "Consulta")
    return pid, cid


def _transcricao(pid, cid, texto, minutos_atras, turnos=None):
    criado = datetime.now(timezone.utc) - timedelta(minutes=minutos_atras)
    TranscricaoRepository(sessao.obter_sessao()).adicionar(
        pid, cid, texto=texto, duracao_s=60, turnos=turnos, criado_em=criado.isoformat()
    )


@pytest.fixture()
def modelo(monkeypatch):
    """Substitui o Gemini e guarda o que foi enviado."""
    import server

    chamadas = []
    resposta = {"valor": '{"itens": []}'}

    def falso(instrucao, conteudo):
        chamadas.append(conteudo)
        valor = resposta["valor"]
        return valor(conteudo) if callable(valor) else valor

    monkeypatch.setattr(server.gemini_connection, "gerar_resposta_unica", falso)
    return chamadas, resposta


def _post(client, headers, pid, cid, **extra):
    return client.post(URL, json={"patient_id": pid, "consultation_id": cid, **extra}, headers=headers)


def test_so_a_janela_entra_no_envio(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    chamadas, resposta = modelo
    resposta["valor"] = json.dumps({"itens": [{"tipo": "pergunta", "texto": "Perguntar sobre febre"}]})
    _transcricao(pid, cid, "trecho recente", minutos_atras=2)
    _transcricao(pid, cid, "trecho antigo", minutos_atras=20)

    r = _post(client, auth_headers("medico"), pid, cid, janela_min=5)

    body = r.get_json()
    assert r.status_code == 200
    assert body["janela_min"] == 5 and body["transcricoes_usadas"] == 1
    assert body["itens"] == [{"tipo": "pergunta", "texto": "Perguntar sobre febre"}]
    assert "trecho recente" in chamadas[0] and "trecho antigo" not in chamadas[0]
    assert body["prompt"] == {"id": rec.PROMPT_ID, "versao": rec.PROMPT_VERSAO}

    _post(client, auth_headers("medico"), pid, cid, janela_min=30)
    assert "trecho antigo" in chamadas[1]


def test_janela_padrao_e_cinco_minutos(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcricao(pid, cid, "ha seis minutos", minutos_atras=6)

    body = _post(client, auth_headers("medico"), pid, cid).get_json()

    assert body["janela_min"] == 5 and body["transcricoes_usadas"] == 0


def test_so_transcricoes_da_propria_consulta(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    outra = ConsultaRepository(sessao.obter_sessao()).criar(pid, "Outra")
    _transcricao(pid, outra, "de outra consulta", minutos_atras=1)
    _transcricao(pid, cid, "desta consulta", minutos_atras=1)

    _post(client, auth_headers("medico"), pid, cid)

    assert "desta consulta" in modelo[0][0] and "de outra consulta" not in modelo[0][0]


def test_texto_sai_anonimizado_e_volta_reidratado(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    chamadas, resposta = modelo
    _transcricao(pid, cid, "Maria Souza relata dor. CPF 529.982.247-25.", minutos_atras=1)

    def ecoa_token(conteudo):
        token = re.search(r"\[[A-Z]+(?:_\d+)?\]", conteudo).group(0)
        return json.dumps({"itens": [{"tipo": "pergunta", "texto": f"Perguntar a {token} sobre febre"}]})

    resposta["valor"] = ecoa_token
    body = _post(client, auth_headers("medico"), pid, cid).get_json()

    assert "Maria" not in chamadas[0] and "529.982.247-25" not in chamadas[0]
    assert "Maria" in body["itens"][0]["texto"]


def test_usa_turnos_com_papel(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcricao(pid, cid, "texto corrido", minutos_atras=1,
                 turnos=[{"role": "Médico", "text": "Tem febre?"}, {"role": "Paciente", "text": "Não"}])

    _post(client, auth_headers("medico"), pid, cid)

    assert "Médico: Tem febre?\nPaciente: Não" in modelo[0][0]


def test_nada_e_gravado_no_prontuario(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    modelo[1]["valor"] = json.dumps({"itens": [{"tipo": "exame", "texto": "Medir pressão"}]})
    _transcricao(pid, cid, "trecho", minutos_atras=1)
    s = sessao.obter_sessao()
    contar = lambda modelo_db: s.scalar(select(func.count()).select_from(modelo_db))  # noqa: E731
    antes = (contar(Mensagem), contar(Transcricao))

    assert _post(client, auth_headers("medico"), pid, cid).status_code == 200

    assert (contar(Mensagem), contar(Transcricao)) == antes


def test_sem_transcricao_nao_chama_o_modelo(client, auth_headers, consulta, modelo):
    pid, cid = consulta

    body = _post(client, auth_headers("medico"), pid, cid).get_json()

    assert body["itens"] == [] and body["transcricoes_usadas"] == 0
    assert "Nenhuma transcrição" in body["message"]
    assert modelo[0] == []


def test_resposta_do_modelo_e_limitada(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    modelo[1]["valor"] = json.dumps({"itens": [{"tipo": "exame", "texto": f"Item {i}"} for i in range(9)]})
    _transcricao(pid, cid, "trecho", minutos_atras=1)

    body = _post(client, auth_headers("medico"), pid, cid).get_json()

    assert len(body["itens"]) == 5
    assert body["recommendation"].splitlines()[0] == "- Item 0"


def test_falha_do_modelo_vira_502(client, auth_headers, consulta, modelo):
    pid, cid = consulta
    _transcricao(pid, cid, "trecho", minutos_atras=1)

    def quebra(_conteudo):
        raise RuntimeError("cota excedida")

    modelo[1]["valor"] = quebra
    r = _post(client, auth_headers("medico"), pid, cid)

    assert r.status_code == 502 and r.get_json()["status"] == "error"


@pytest.mark.parametrize("corpo, status", [
    (None, 400),
    ({"consultation_id": "x"}, 400),
    ({"janela_min": 0}, 400),
    ({"janela_min": "abc"}, 400),
])
def test_validacao(client, auth_headers, consulta, modelo, corpo, status):
    pid, cid = consulta
    payload = None if corpo is None else {"patient_id": pid, "consultation_id": cid, **corpo}
    if corpo == {"consultation_id": "x"}:
        payload = corpo
    r = client.post(URL, json=payload, headers=auth_headers("medico")) if payload is not None else \
        client.post(URL, data="nao e json", headers=auth_headers("medico"))

    assert r.status_code == status


def test_consulta_de_outro_paciente_404(client, auth_headers, consulta, modelo):
    pid, _cid = consulta
    outro = PacienteRepository(sessao.obter_sessao()).criar(nome="Outro", medico_id=TEST_USER_ID)["id"]
    cid_outro = ConsultaRepository(sessao.obter_sessao()).criar(outro, "C")

    assert _post(client, auth_headers("medico"), pid, cid_outro).status_code == 404


def test_outro_medico_403(client, consulta, modelo, monkeypatch):
    from backend import auth_decorators

    pid, cid = consulta
    monkeypatch.setattr(auth_decorators, "get_user_from_token", lambda _t: (
        {"id": DOCTOR_B, "email": "b@example.com", "name": "B", "profiles": ["medico"], "active": True},
        {"profile": "medico"},
    ))

    r = _post(client, {"Authorization": "Bearer x"}, pid, cid)

    assert r.status_code == 403


def test_exige_token(client, consulta):
    pid, cid = consulta

    assert client.post(URL, json={"patient_id": pid, "consultation_id": cid}).status_code == 401
