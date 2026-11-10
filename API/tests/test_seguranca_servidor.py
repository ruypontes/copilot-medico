"""
Configuracao segura do servidor: modo debug, interface de rede, tamanho
maximo da requisicao e log sem conteudo da consulta.
"""
import io
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# python server.py: debug e host
# ---------------------------------------------------------------------------

def test_servidor_sobe_sem_debug_e_so_nesta_maquina_por_padrao(flask_app):
    import server

    assert server.opcoes_do_servidor({}) == ("127.0.0.1", False)


def test_debug_e_host_vem_do_ambiente(flask_app):
    import server

    host, debug = server.opcoes_do_servidor({"FLASK_DEBUG": "1", "FLASK_RUN_HOST": "0.0.0.0"})

    assert (host, debug) == ("0.0.0.0", True)


def test_debug_so_liga_com_valor_explicito(flask_app):
    import server

    for valor in ("", "0", "false", "nao"):
        assert server.opcoes_do_servidor({"FLASK_DEBUG": valor})[1] is False


def test_docker_publica_api_e_banco_so_no_localhost():
    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:3001:3001"' in compose
    assert '"127.0.0.1:5432:5432"' in compose
    assert not re.search(r'-\s*"(3001|5432):', compose)


def test_dockerfile_nao_liga_o_debug():
    dockerfile = (RAIZ / "API" / "Dockerfile").read_text(encoding="utf-8")

    assert "FLASK_RUN_HOST=0.0.0.0" in dockerfile
    assert "FLASK_DEBUG" not in dockerfile


# ---------------------------------------------------------------------------
# Tamanho maximo da requisicao
# ---------------------------------------------------------------------------

def test_limite_cobre_a_maior_parte_de_audio(flask_app):
    from backend.config import settings

    assert flask_app.config["MAX_CONTENT_LENGTH"] > settings.audio_chunk_max_mb * 1024 * 1024


def test_upload_acima_do_limite_responde_413_em_json(flask_app, auth_client, monkeypatch):
    monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 1024)

    resposta = auth_client.post(
        "/api/upload-pdf",
        data={"pdf": (io.BytesIO(b"x" * 4096), "exame.pdf")},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 413
    assert resposta.get_json()["status"] == "error"


def test_audio_acima_do_limite_responde_413_e_nao_chega_na_rota(flask_app, auth_client, monkeypatch):
    import server

    monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 1024)
    chamadas = []
    monkeypatch.setattr(server.audio_chunks, "salvar_avulso", lambda *a, **k: chamadas.append(a))

    resposta = auth_client.post(
        "/api/transcribe_audio",
        data={"audio_file": (io.BytesIO(b"x" * 4096), "consulta.wav"), "patient_id": "p1"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 413
    assert chamadas == []


# ---------------------------------------------------------------------------
# Log sem conteudo da consulta
# ---------------------------------------------------------------------------

def test_mensagem_mal_formatada_nao_vai_para_o_log(capsys):
    from backend.llm import gemini

    gemini._conversa([{"texto": "Maria Souza, CPF 123.456.789-09, refere dor"}], "oi")

    saida = capsys.readouterr().out
    assert "mal formatada" in saida
    assert "Maria" not in saida
    assert "123.456.789-09" not in saida
