"""Auditoria de envios externos e anonimizacao dos turnos (B36 / US016-CA001, CA004).

Duas garantias, cada uma com seu teste:

1. TODO envio a um provedor externo deixa uma linha na tabela `envio_externo`
   (quando, qual consulta, qual provedor, tamanho) - e NENHUM conteudo.
2. O que a transcricao grava (texto e turnos) sai do Google SR e entra no banco
   ja anonimizado.

Como em test_anonimizacao_rotas.py, PII e plantada nas requisicoes e o teste
inspeciona o que de fato foi gravado - o anonimizador estar pronto nao basta,
e preciso estar ligado em cada caminho.
"""
from __future__ import annotations

import ast
import inspect
import io
import json
import pathlib
import re
import sys

import pytest
from sqlalchemy import DateTime, Integer, String, Uuid

from ids import TEST_USER_ID
from models import EnvioExterno
from repositories import AuditoriaEnvioRepository, TranscricaoRepository, sessao

NOME = "Maria Souza"
CPF = "529.982.247-25"
TELEFONE = "(81) 99876-5432"
EMAIL = "maria.souza@clinica.com.br"
SENSIVEIS = [NOME, CPF, TELEFONE, EMAIL]
PADROES = {
    "CPF": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "telefone": re.compile(r"\(\d{2}\)\s?\d{4,5}-\d{4}"),
}

API_DIR = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

@pytest.fixture()
def paciente(auth_client):
    resposta = auth_client.post("/api/patients", json={"name": NOME})
    assert resposta.status_code == 201
    return resposta.get_json()


@pytest.fixture()
def gemini_falso(monkeypatch):
    """Provedor falso: nada sai da maquina nos testes."""
    import server

    enviados: list[str] = []

    def falso_send_message(patient_id, consultation_id, message_text):
        enviados.append(message_text)
        return "Resposta do modelo."

    monkeypatch.setattr(server.gemini_connection, "send_message", falso_send_message)
    return enviados


def _envios(consulta_id=None):
    return AuditoriaEnvioRepository(sessao.obter_sessao()).listar(consulta_id)


def _sem_pii(texto: str) -> None:
    for valor in SENSIVEIS:
        assert valor not in texto, f"{valor!r} foi gravado em claro"
    for rotulo, padrao in PADROES.items():
        achado = padrao.search(texto)
        assert achado is None, f"padrao de {rotulo} gravado em claro: {achado.group(0)!r}"


# ---------------------------------------------------------------------------
# Modelo e repositorio: a tabela so guarda metadados
# ---------------------------------------------------------------------------

def test_tabela_so_tem_colunas_de_metadados():
    """Barreira estrutural: ninguem acrescenta, sem querer, uma coluna de conteudo.

    Texto livre ou JSON aqui transformaria a auditoria em uma copia do que foi
    enviado - o oposto do que a US016-CA004 pede.
    """
    permitidos = (Uuid, DateTime, Integer)
    for coluna in EnvioExterno.__table__.columns:
        tipo = coluna.type
        if isinstance(tipo, String):
            assert tipo.length is not None and tipo.length <= 32, (
                f"coluna {coluna.name}: texto livre na auditoria (use rotulos curtos)"
            )
        else:
            assert isinstance(tipo, permitidos), f"coluna {coluna.name}: tipo {tipo!r} nao permitido"


def test_registrar_nao_tem_parametro_de_conteudo():
    parametros = set(inspect.signature(AuditoriaEnvioRepository.registrar).parameters)
    assert parametros == {
        "self", "provedor", "operacao", "tamanho_bytes", "consulta_id", "medico_id", "chamadas",
    }


def test_registrar_e_listar(temp_db_file, paciente):
    consulta = paciente["first_consultation_id"]
    repo = AuditoriaEnvioRepository(sessao.obter_sessao())

    registro = repo.registrar("gemini", "chat", 120, consulta_id=consulta, medico_id=TEST_USER_ID)

    assert registro["provider"] == "gemini"
    assert registro["operation"] == "chat"
    assert registro["size_bytes"] == 120
    assert registro["calls"] == 1
    assert registro["consultation_id"] == consulta
    assert registro["doctor_id"] == TEST_USER_ID
    assert registro["created_at"]
    assert repo.listar(consulta) == [registro]


def test_ids_invalidos_viram_nulo_e_numeros_sao_saneados(temp_db_file):
    repo = AuditoriaEnvioRepository(sessao.obter_sessao())

    registro = repo.registrar("gemini", "chat", -5, consulta_id="nao-e-uuid", medico_id=None, chamadas=0)

    assert registro["consultation_id"] is None
    assert registro["size_bytes"] == 0
    assert registro["calls"] == 1


def test_uuid_valido_mas_inexistente_nao_perde_a_linha(temp_db_file):
    """No Postgres a FK recusaria o INSERT; a linha precisa ser gravada sem o vinculo."""
    repo = AuditoriaEnvioRepository(sessao.obter_sessao())
    fantasma = "ffffffff-ffff-4fff-8fff-ffffffffffff"

    registro = repo.registrar("gemini", "chat", 10, consulta_id=fantasma, medico_id=fantasma)

    assert registro["consultation_id"] is None
    assert registro["doctor_id"] is None
    assert repo.listar() == [registro]


def test_listar_filtra_por_consulta_e_limita(temp_db_file, paciente):
    consulta = paciente["first_consultation_id"]
    repo = AuditoriaEnvioRepository(sessao.obter_sessao())
    for _ in range(3):
        repo.registrar("gemini", "chat", 10, consulta_id=consulta)
    repo.registrar("gemini", "chat", 10)  # sem consulta

    assert len(repo.listar(consulta)) == 3
    assert len(repo.listar()) == 4
    assert len(repo.listar(limite=2)) == 2
    assert repo.listar("nao-e-uuid") == []


# ---------------------------------------------------------------------------
# Gemini: cada rota registra um envio, sem conteudo
# ---------------------------------------------------------------------------

def test_chat_registra_envio_ao_gemini(auth_client, paciente, gemini_falso):
    consulta = paciente["first_consultation_id"]
    texto = f"{NOME}, CPF {CPF}. Queixa de cefaleia ha 3 dias."

    resposta = auth_client.post("/api/chat", json={
        "message": texto, "patient_id": paciente["patient_id"], "consultation_id": consulta,
    })

    assert resposta.status_code == 200
    envios = _envios(consulta)
    assert len(envios) == 1
    assert envios[0]["provider"] == "gemini"
    assert envios[0]["operation"] == "chat"
    assert envios[0]["consultation_id"] == consulta
    assert envios[0]["doctor_id"] == TEST_USER_ID
    # o tamanho cobre pelo menos o texto que de fato saiu (ja anonimizado)
    assert envios[0]["size_bytes"] >= len(gemini_falso[0].encode("utf-8")) > 0


def test_auditoria_nao_guarda_conteudo(auth_client, paciente, gemini_falso):
    """CA004: 'sem conteudo'. Nem o texto clinico, nem a PII, nem o token."""
    consulta = paciente["first_consultation_id"]
    auth_client.post("/api/chat", json={
        "message": f"{NOME}, CPF {CPF}, telefone {TELEFONE}. Dor toracica intensa.",
        "patient_id": paciente["patient_id"], "consultation_id": consulta,
    })

    bruto = json.dumps(_envios(consulta), ensure_ascii=False).lower()

    for proibido in (*SENSIVEIS, TELEFONE, "toracica", "intensa", "[cpf_1]", "[paciente"):
        assert proibido.lower() not in bruto, f"{proibido!r} apareceu na auditoria"


def test_tamanho_cresce_com_o_historico(auth_client, paciente, gemini_falso):
    """O Gemini e sem estado: cada chamada reenvia o historico, e o tamanho reflete isso."""
    comum = {"patient_id": paciente["patient_id"], "consultation_id": paciente["first_consultation_id"]}
    auth_client.post("/api/chat", json={"message": "Primeira mensagem sobre febre.", **comum})
    auth_client.post("/api/chat", json={"message": "Segunda mensagem sobre febre.", **comum})

    segundo, primeiro = _envios(paciente["first_consultation_id"])  # mais recente primeiro
    assert segundo["size_bytes"] > primeiro["size_bytes"]


def test_extensao_registra_envio_ao_gemini(auth_client, paciente, gemini_falso):
    consulta = paciente["first_consultation_id"]

    resposta = auth_client.post("/api/extension/extracted-data", json={
        "patient_id": paciente["patient_id"], "consultation_id": consulta,
        "extracted_content": [{"role": "queixa", "text": "dor toracica ha 2 horas"}],
    })

    assert resposta.status_code == 200
    envios = _envios(consulta)
    assert [(e["provider"], e["operation"]) for e in envios] == [("gemini", "extensao")]


def test_upload_pdf_registra_envio_ao_gemini(auth_client, paciente, gemini_falso):
    consulta = paciente["first_consultation_id"]

    resposta = auth_client.post(
        "/api/upload-pdf",
        data={
            "pdf": (io.BytesIO(b"Laudo: hemoglobina 13.5."), "laudo.pdf"),
            "patient_id": paciente["patient_id"], "consultation_id": consulta,
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    assert [(e["provider"], e["operation"]) for e in _envios(consulta)] == [("gemini", "pdf")]


def test_recomendacao_registra_envio_ao_gemini(auth_client, paciente, gemini_falso):
    consulta = paciente["first_consultation_id"]

    resposta = auth_client.post("/api/recommendations", json={
        "patient_id": paciente["patient_id"], "consultation_id": consulta,
    })

    assert resposta.status_code == 200
    assert [(e["provider"], e["operation"]) for e in _envios(consulta)] == [("gemini", "recomendacao")]


def test_falha_da_auditoria_nao_bloqueia_o_atendimento(auth_client, paciente, gemini_falso, monkeypatch, capsys):
    """Decisao: fail-open. Uma falha do banco de auditoria nao derruba o chat."""
    import server

    def quebrado():
        raise RuntimeError("banco de auditoria indisponivel")

    monkeypatch.setattr(server, "_auditoria", quebrado)
    comum = {"patient_id": paciente["patient_id"], "consultation_id": paciente["first_consultation_id"]}

    primeira = auth_client.post("/api/chat", json={"message": f"{NOME} com febre.", **comum})
    segunda = auth_client.post("/api/chat", json={"message": "Continua com febre.", **comum})

    assert primeira.status_code == 200 and segunda.status_code == 200
    linhas = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[AUDITORIA]")]
    assert linhas and all("RuntimeError" in l for l in linhas)
    # so o tipo do erro: a linha de auditoria nao pode carregar conteudo
    assert not any(NOME in l or "febre" in l for l in linhas)


# ---------------------------------------------------------------------------
# Barreiras estruturais: nenhum envio futuro escapa da auditoria
# ---------------------------------------------------------------------------

def _arquivos_de_producao():
    ignorados = {"tests", "migrations", "scripts", "__pycache__", "venv", ".venv"}
    for caminho in API_DIR.rglob("*.py"):
        partes = set(caminho.relative_to(API_DIR).parts)
        if not partes & ignorados and not any(p.startswith("vosk-model") for p in partes):
            yield caminho


def test_gemini_so_e_chamado_pelo_wrapper_auditado():
    """`send_message` so pode ser chamado dentro de `_enviar_ao_gemini` (server.py)."""
    fonte = (API_DIR / "server.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    chamadas_fora = []
    for funcao in ast.walk(arvore):
        if not isinstance(funcao, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for no in ast.walk(funcao):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr == "send_message"
                and funcao.name != "_enviar_ao_gemini"
            ):
                chamadas_fora.append(f"{funcao.name}:{no.lineno}")

    assert not chamadas_fora, (
        "chamada direta a send_message sem auditoria em: " + ", ".join(chamadas_fora)
        + " - use _enviar_ao_gemini(operacao, ...)"
    )


def test_google_sr_so_e_chamado_pelo_transcritor_auditado():
    """`recognize_google` so existe dentro de TranscritorVoz.transcrever."""
    ocorrencias = []
    for caminho in _arquivos_de_producao():
        if "recognize_google(" in caminho.read_text(encoding="utf-8", errors="replace"):
            ocorrencias.append(caminho.relative_to(API_DIR).as_posix())

    # Os scripts manuais de microfone em processador_voz/test_*.py nao rodam no servidor.
    ocorrencias = [o for o in ocorrencias if not pathlib.PurePosixPath(o).name.startswith("test_")]
    assert ocorrencias == ["backend/processador_voz/processador_voz.py"], (
        f"envio ao Google SR fora do TranscritorVoz auditado: {ocorrencias}"
    )


# ---------------------------------------------------------------------------
# Google SR: o gancho do TranscritorVoz (classe REAL, nao o stub da suite)
# ---------------------------------------------------------------------------

@pytest.fixture()
def transcritor_real(real_module, monkeypatch):
    """Devolve (classe real, lista de eventos) com um reconhecedor falso.

    O conftest troca `speech_recognition` por um stub sem `AudioData`; ele e
    acrescentado aqui so para o isinstance do TranscritorVoz.
    """
    # O conftest stubba o PACOTE e o submodulo; sem trocar o pacote antes, o
    # import do submodulo real nao encontra o arquivo.
    real_module("backend.processador_voz")
    modulo = real_module("backend.processador_voz.processador_voz")
    sr = sys.modules["speech_recognition"]

    class AudioFalso:
        def __init__(self, frame_data):
            self.frame_data = frame_data

    eventos: list = []
    monkeypatch.setattr(sr, "AudioData", AudioFalso, raising=False)
    monkeypatch.setattr(
        sr.Recognizer, "recognize_google",
        lambda self, audio, language=None: eventos.append(("google", len(audio.frame_data))) or "ok",
    )
    monkeypatch.setattr(modulo.TranscritorVoz, "auditor", None)
    return modulo.TranscritorVoz, AudioFalso, eventos


def test_transcritor_audita_antes_de_enviar_ao_google(transcritor_real, monkeypatch):
    TranscritorVoz, AudioFalso, eventos = transcritor_real
    monkeypatch.setattr(TranscritorVoz, "auditor", lambda provedor, tamanho: eventos.append((provedor, tamanho)))

    texto = TranscritorVoz().transcrever(AudioFalso(b"\x00" * 3200))

    assert texto == "ok"
    # a auditoria vem ANTES do envio: se o processo morrer no meio, o registro existe
    assert eventos == [("google_sr", 3200), ("google", 3200)]


def test_transcritor_funciona_se_o_auditor_falhar(transcritor_real, monkeypatch, capsys):
    TranscritorVoz, AudioFalso, eventos = transcritor_real

    def quebrado(provedor, tamanho):
        raise RuntimeError("auditoria fora do ar")

    monkeypatch.setattr(TranscritorVoz, "auditor", quebrado)

    assert TranscritorVoz().transcrever(AudioFalso(b"\x00" * 100)) == "ok"
    assert "[AUDITORIA]" in capsys.readouterr().out


def test_transcritor_sem_auditor_continua_funcionando(transcritor_real):
    TranscritorVoz, AudioFalso, _ = transcritor_real
    assert TranscritorVoz.auditor is None
    assert TranscritorVoz().transcrever(AudioFalso(b"\x00" * 100)) == "ok"


def test_audio_invalido_nao_e_enviado_nem_auditado(transcritor_real, monkeypatch):
    TranscritorVoz, _, eventos = transcritor_real
    monkeypatch.setattr(TranscritorVoz, "auditor", lambda provedor, tamanho: eventos.append("auditado"))

    assert TranscritorVoz().transcrever("nao e AudioData").startswith("Erro")
    assert eventos == []


# ---------------------------------------------------------------------------
# POST /api/transcribe_audio: turnos sem PII + auditoria do Google SR
# ---------------------------------------------------------------------------

TURNOS_COM_PII = [
    {"role": "Médico", "role_key": "doctor", "speaker_id": 0,
     "text": f"Bom dia, {NOME}. Confirma o CPF {CPF}?"},
    {"role": "Paciente", "role_key": "patient", "speaker_id": 1,
     "text": f"Confirmo. Meu telefone e {TELEFONE} e o e-mail {EMAIL}. Estou com febre."},
]


class _DiarizadorFalso:
    """Imita o Diarizador: cada trecho vai ao Google (gancho) e devolve turnos com PII."""

    def __init__(self, server, turnos, trechos=(3200, 6400, 1600), erro_no_fim=False, texto=None):
        self.server, self.turnos, self.trechos = server, turnos, trechos
        self.erro_no_fim, self.texto = erro_no_fim, texto

    def processar_audio(self, caminho):
        for tamanho in self.trechos:
            self.server.TranscritorVoz.auditor("google_sr", tamanho)
        if self.erro_no_fim:
            raise RuntimeError("diarizacao falhou depois de enviar trechos")
        completo = "\n".join(f"{t['role']}: {t['text']}" for t in self.turnos)
        return {"full_text": self.texto or completo, "dialogue": self.turnos, "speakers_count": 2}


def _enviar_audio(auth_client, paciente, nome_arquivo="consulta_maria_souza.wav", consulta=True):
    dados = {
        "patient_id": paciente["patient_id"],
        "duration": "5",
        "audio_file": (io.BytesIO(b"RIFF....WAVE"), nome_arquivo),
    }
    if consulta:
        dados["consultation_id"] = paciente["first_consultation_id"]
    return auth_client.post("/api/transcribe_audio", data=dados, content_type="multipart/form-data")


def test_transcricao_grava_turnos_anonimizados(auth_client, paciente, monkeypatch):
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))

    resposta = _enviar_audio(auth_client, paciente)

    assert resposta.status_code == 200
    gravado = TranscricaoRepository(sessao.obter_sessao()).listar(paciente["patient_id"])[0]
    _sem_pii(gravado["text"])
    for turno in gravado["dialogue"]:
        _sem_pii(turno["text"])
    # o conteudo clinico e os rotulos do turno sobrevivem: senao a transcricao perde o sentido
    assert "febre" in gravado["dialogue"][1]["text"]
    assert [(t["role"], t["role_key"], t["speaker_id"]) for t in gravado["dialogue"]] == [
        ("Médico", "doctor", 0), ("Paciente", "patient", 1),
    ]
    # o mesmo CPF recebe o mesmo token no texto corrido e no turno
    token = re.search(r"\[CPF_\d+\]", gravado["dialogue"][0]["text"]).group(0)
    assert token in gravado["text"]


def test_transcricao_guarda_so_a_extensao_do_arquivo(auth_client, paciente, monkeypatch):
    """O nome do arquivo costuma trazer o nome do paciente."""
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))

    _enviar_audio(auth_client, paciente, nome_arquivo="consulta_maria_souza.wav")

    gravado = TranscricaoRepository(sessao.obter_sessao()).listar(paciente["patient_id"])[0]
    assert gravado["audio"]["filename"] == "audio.wav"
    assert "maria" not in json.dumps(gravado["audio"]).lower()


def test_transcricao_devolve_ao_medico_o_texto_real(auth_client, paciente, monkeypatch):
    """US016-CA002: o banco tem tokens; a tela do medico recebe os valores reais."""
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))

    corpo = _enviar_audio(auth_client, paciente).get_json()

    assert NOME in corpo["transcription"] and CPF in corpo["transcription"]
    assert CPF in corpo["log_entry"]["dialogue"][0]["text"]
    assert TELEFONE in corpo["log_entry"]["dialogue"][1]["text"]
    assert CPF in corpo["log_entry"]["text"]


def test_listagem_da_transcricao_nao_traz_pii(auth_client, paciente, monkeypatch):
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))
    _enviar_audio(auth_client, paciente)

    logs = auth_client.get(f"/api/patients/{paciente['patient_id']}/transcription-log").get_json()["logs"]

    _sem_pii(json.dumps(logs, ensure_ascii=False))


def test_transcricao_registra_o_envio_ao_google_sr(auth_client, paciente, monkeypatch):
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))

    _enviar_audio(auth_client, paciente)

    envios = _envios(paciente["first_consultation_id"])
    assert len(envios) == 1, "uma linha por transcricao, nao uma por trecho"
    assert envios[0]["provider"] == "google_sr"
    assert envios[0]["operation"] == "transcricao"
    assert envios[0]["calls"] == 3
    assert envios[0]["size_bytes"] == 3200 + 6400 + 1600
    assert envios[0]["doctor_id"] == TEST_USER_ID
    bruto = json.dumps(envios, ensure_ascii=False)
    for valor in SENSIVEIS:
        assert valor not in bruto


def test_envio_parcial_e_registrado_mesmo_se_a_diarizacao_falhar(auth_client, paciente, monkeypatch):
    """O que ja foi ao Google precisa constar, mesmo que a requisicao termine em erro."""
    import server

    monkeypatch.setattr(
        server, "audio_processor",
        _DiarizadorFalso(server, TURNOS_COM_PII, trechos=(3200, 3200), erro_no_fim=True),
    )

    _enviar_audio(auth_client, paciente)

    envios = _envios(paciente["first_consultation_id"])
    assert [(e["provider"], e["calls"], e["size_bytes"]) for e in envios] == [("google_sr", 2, 6400)]


def test_audio_sem_fala_tambem_e_auditado(auth_client, paciente, monkeypatch):
    """Silencio/ruido nao grava transcricao, mas o audio ja foi ao Google."""
    import server

    monkeypatch.setattr(
        server, "audio_processor",
        _DiarizadorFalso(server, [], trechos=(1600,), texto="Não foi possível entender o áudio"),
    )

    corpo = _enviar_audio(auth_client, paciente).get_json()

    assert corpo["is_error"] is True
    assert TranscricaoRepository(sessao.obter_sessao()).listar(paciente["patient_id"]) == []
    assert [(e["provider"], e["size_bytes"]) for e in _envios(paciente["first_consultation_id"])] == [
        ("google_sr", 1600)
    ]


def test_transcricao_sem_consulta_ainda_e_auditada(auth_client, paciente, monkeypatch):
    import server

    monkeypatch.setattr(server, "audio_processor", _DiarizadorFalso(server, TURNOS_COM_PII))

    resposta = _enviar_audio(auth_client, paciente, consulta=False)

    assert resposta.status_code == 200
    envios = _envios()
    assert len(envios) == 1 and envios[0]["consultation_id"] is None


# ---------------------------------------------------------------------------
# GET /api/audit/external-sends
# ---------------------------------------------------------------------------

def test_consulta_da_auditoria_exige_administrador(client, auth_client, auth_headers, paciente, gemini_falso):
    auth_client.post("/api/chat", json={
        "message": "Dor de cabeca.", "patient_id": paciente["patient_id"],
        "consultation_id": paciente["first_consultation_id"],
    })

    resposta = auth_client.get("/api/audit/external-sends")
    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["count"] == 1
    assert corpo["external_sends"][0]["operation"] == "chat"

    # Cada chamada de `auth_headers(perfil)` troca o perfil de TODOS os clientes
    # autenticados do teste; por isso os casos de negacao vem depois.
    assert client.get("/api/audit/external-sends").status_code == 401
    assert client.get("/api/audit/external-sends", headers=auth_headers("medico")).status_code == 403


def test_consulta_da_auditoria_filtra_e_limita(auth_client, paciente, gemini_falso):
    comum = {"patient_id": paciente["patient_id"], "consultation_id": paciente["first_consultation_id"]}
    for _ in range(3):
        auth_client.post("/api/chat", json={"message": "Mais uma mensagem.", **comum})

    todos = auth_client.get("/api/audit/external-sends").get_json()
    filtrado = auth_client.get(f"/api/audit/external-sends?consultation_id={paciente['first_consultation_id']}").get_json()
    limitado = auth_client.get("/api/audit/external-sends?limit=2").get_json()
    outra = auth_client.get("/api/audit/external-sends?consultation_id=nao-e-uuid").get_json()

    assert todos["count"] == filtrado["count"] == 3
    assert limitado["count"] == 2
    assert outra["count"] == 0
