"""B60 - teste de vazamento completo: áudio transcrito e PDF (US016-CA003).

O B47 cobre /soap e /api/chat com a transcrição semeada direto no banco. Este
teste percorre os dois caminhos que ficaram de fora, ponta a ponta, com os
mesmos 20 casos sintéticos da B45 e o MESMO verificador do B47 (critérios,
lacunas conhecidas e nomes de terceiros vêm de test_b47_vazamento_pii):

1. Áudio transcrito: a extensão envia o áudio em partes, o provedor de
   transcrição (falso) devolve a fala do caso com turnos, e o texto segue o
   caminho real da extensão: /api/chat (useAudioRecording.ts manda a
   transcrição para o chat), /api/recommendations e /soap.
2. PDF: um PDF de verdade com a transcrição do caso é gerado e lido pelo
   extrator real (PyPDF2), e passa por /api/upload-pdf e depois por /soap,
   que inclui o PDF em "documentos anexados".

O que conta como payload: TUDO o que iria ao Gemini. O chat inclui o
histórico da consulta lido do banco, como o backend/llm/chat.py real faz;
uma mensagem gravada sem anonimizar apareceria aqui. Além disso, o log do
servidor não pode ter nenhuma PII plantada, nem as lacunas conhecidas: log
não leva conteúdo clínico (RNF08).

Fora de escopo, por decisão registrada no docs/08: o ÁUDIO bruto que vai ao
provedor de transcrição não tem como ser anonimizado (consentimento +
provedor sem retenção). O que este teste garante é que o TEXTO transcrito
não sai sem anonimização.
"""
from __future__ import annotations

import io
import json
import wave

import pytest
from werkzeug.datastructures import FileStorage

# Mesmo verificador e mesmas lacunas do B47: um critério só para todas as rotas.
import test_b47_vazamento_pii as b47

from backend import recomendacoes
from backend.anonimizacao import ner as ner_mod
from backend.config import settings
from ids import TEST_USER_ID
from repositories import ConsultaRepository, MensagemRepository, PacienteRepository, sessao

GRAVACAO = "gravacao-b60-0001"


# ---------------------------------------------------------------------------
# Modo determinístico e cofre: iguais às fixtures do B47
# ---------------------------------------------------------------------------

@pytest.fixture()
def ner_desligado(monkeypatch):
    """Só regex + nomes do cadastro, como no CI (sem spaCy). Ver o B47."""
    monkeypatch.setattr(ner_mod, "_nlp_cache", False)


@pytest.fixture()
def cofre_aberto(monkeypatch):
    """Cofre aberto: o mapa da consulta persiste e os tokens ficam estáveis
    entre transcrição, chat, sugestões e SOAP (B25/B26)."""
    import server
    from backend.anonimizacao.cripto import criar_cofre

    aberto = criar_cofre("senha-de-teste-b60")[0]
    monkeypatch.setattr(server, "_cofre_atual", lambda: aberto)
    return aberto


# ---------------------------------------------------------------------------
# LLM falso: guarda tudo o que sairia para o Gemini
# ---------------------------------------------------------------------------

def _texto_do_historico(historico: list[dict]) -> str:
    return "\n".join(
        parte.get("text", "") if isinstance(parte, dict) else str(parte)
        for mensagem in historico
        for parte in mensagem.get("parts") or []
    )


class _LlmFalso:
    """No lugar de backend.llm.chat. Cada chamada vira um payload (rota, texto)."""

    def __init__(self) -> None:
        self.payloads: list[tuple[str, str]] = []

    def send_message(self, patient_id, consultation_id, message_text):
        # Igual ao chat real: histórico da consulta do banco + mensagem nova.
        historico = MensagemRepository(sessao.obter_sessao()).historico(consultation_id)
        self.payloads.append(("chat", f"{_texto_do_historico(historico)}\n\n{message_text}"))
        return "Resposta simulada da IA."

    def gerar_resposta_unica(self, instrucao, conteudo, response_schema=None):
        if instrucao == recomendacoes.INSTRUCAO:
            self.payloads.append(("recomendacoes", f"{instrucao}\n\n{conteudo}"))
            return json.dumps({"itens": [{"tipo": "pergunta", "texto": "Febre associada?"}]})
        self.payloads.append(("soap", f"{instrucao}\n\n{conteudo}"))
        return json.dumps(b47._SOAP_VALIDO)

    def rotas(self) -> set[str]:
        return {rota for rota, _ in self.payloads}


@pytest.fixture()
def llm(monkeypatch):
    import server

    falso = _LlmFalso()
    monkeypatch.setattr(server.chat_ia, "send_message", falso.send_message)
    monkeypatch.setattr(server.chat_ia, "gerar_resposta_unica", falso.gerar_resposta_unica)
    return falso


# ---------------------------------------------------------------------------
# Áudio: provedor de transcrição falso que "ouve" a fala do caso
# ---------------------------------------------------------------------------

_PAPEIS = {"médico": ("Médico", "doctor", 0), "paciente": ("Paciente", "patient", 1)}


def _turnos_do_caso(caso: dict) -> list[dict]:
    """A transcrição do caso ("Médico: ..." / "Paciente: ...") como turnos,
    no formato do TranscriptionProvider (backend/transcription/provider.py)."""
    turnos = []
    for linha in caso["transcricao"].splitlines():
        falante, sep, texto = linha.partition(":")
        if not sep or not texto.strip():
            continue
        role, role_key, speaker_id = _PAPEIS.get(
            falante.strip().lower(), ("Falante não identificado", "unknown", None))
        turnos.append({"role": role, "role_key": role_key, "text": texto.strip(),
                       "speaker_id": speaker_id})
    return turnos


class _ProvedorDoCaso:
    nome = "gemini"

    def __init__(self, caso: dict) -> None:
        self.turnos = _turnos_do_caso(caso)

    def processar_audio(self, caminho):
        return {
            "full_text": "\n".join(f"{t['role']}: {t['text']}" for t in self.turnos),
            "dialogue": self.turnos,
            "speakers_count": 2,
            "duration": 60.0,
        }


@pytest.fixture()
def pasta_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audio_chunks_dir", str(tmp_path / "audio"))


def _wav_de_silencio(segundos: int = 1, taxa: int = 100) -> io.BytesIO:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(b"\x00\x00" * segundos * taxa)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# PDF: gerado de verdade e lido pelo extrator real (PyPDF2)
# ---------------------------------------------------------------------------

def _escapar_pdf(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf(linhas: list[str], por_pagina: int = 60) -> bytes:
    """PDF mínimo (Helvetica, WinAnsi), uma linha de texto por linha da lista.

    Sem quebra automática de linha: um telefone partido entre duas linhas
    mudaria o que o teste mede (ver a observação no PR do B60).
    """
    paginas = [linhas[i:i + por_pagina] for i in range(0, len(linhas), por_pagina)] or [[]]
    objetos: list[bytes] = []

    def novo(conteudo: bytes) -> int:
        objetos.append(conteudo)
        return len(objetos)

    catalogo = novo(b"")  # preenchidos depois de saber os ids
    raiz_paginas = novo(b"")
    fonte = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    ids_paginas = []
    for pagina in paginas:
        texto = "BT /F1 9 Tf 11 TL 36 806 Td\n" + "".join(
            f"({_escapar_pdf(linha)}) Tj T*\n" for linha in pagina) + "ET"
        corpo = texto.encode("cp1252", errors="replace")
        conteudo = novo(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(corpo), corpo))
        ids_paginas.append(novo(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (raiz_paginas, fonte, conteudo)))
    objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % raiz_paginas
    objetos[raiz_paginas - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % i for i in ids_paginas), len(ids_paginas))

    saida = io.BytesIO()
    saida.write(b"%PDF-1.4\n")
    deslocamentos = []
    for numero, objeto in enumerate(objetos, start=1):
        deslocamentos.append(saida.tell())
        saida.write(b"%d 0 obj\n%s\nendobj\n" % (numero, objeto))
    inicio_xref = saida.tell()
    saida.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1))
    for deslocamento in deslocamentos:
        saida.write(b"%010d 00000 n \n" % deslocamento)
    saida.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objetos) + 1, catalogo, inicio_xref))
    return saida.getvalue()


def _pdf_do_caso(caso: dict) -> bytes:
    """Relatório como os que o médico anexa: cabeçalho do paciente + a consulta."""
    paciente = b47._escolher_nome_do_paciente(caso)
    return _pdf([
        "Relatório de atendimento (documento fictício de teste)",
        f"Paciente: {paciente}",
        "",
        *caso["transcricao"].splitlines(),
    ])


@pytest.fixture()
def leitor_pdf_real(monkeypatch, real_module):
    """O extrator de verdade (backend/pdf_reader.py com PyPDF2) no lugar do stub."""
    pytest.importorskip("PyPDF2", reason="PyPDF2 não instalado (está no requirements-dev.txt)")
    import server

    leitor = real_module("backend.pdf_reader")
    monkeypatch.setattr(server, "pdf_reader", leitor)
    return leitor


# ---------------------------------------------------------------------------
# Verificação
# ---------------------------------------------------------------------------

def _paciente_e_consulta(caso: dict) -> tuple[str, str]:
    s = sessao.obter_sessao()
    pid = PacienteRepository(s).criar(nome=b47._escolher_nome_do_paciente(caso),
                                      medico_id=TEST_USER_ID)["id"]
    return pid, ConsultaRepository(s).criar(pid, "Consulta B60")


def _assert_sem_vazamento(caso: dict, llm: _LlmFalso, rotas: set[str]) -> None:
    """Mesmas três checagens do B47, em cada payload que sairia ao Gemini."""
    assert llm.rotas() == rotas, (
        f"{caso['id']}: esperava chamadas ao Gemini por {sorted(rotas)}, "
        f"houve {sorted(llm.rotas())}."
    )
    for rota, payload in llm.payloads:
        vazamentos = b47._detectar_vazamentos(caso, payload, ignorar_lacunas=True)
        assert not vazamentos, (
            f"{caso['id']}: PII vazou no payload de {rota!r}: {vazamentos}. "
            f"Lacuna nova do anonimizador só entra em LACUNAS_CONHECIDAS (B47) "
            f"com aprovação do time."
        )
        padroes = b47._detectar_padroes_genericos(payload)
        assert not padroes, f"{caso['id']}: padrão genérico de PII em {rota!r}: {padroes}."
    # O payload principal (com a consulta inteira) não pode ter perdido o conteúdo.
    maior = max((p for _rota, p in llm.payloads), key=len)
    b47._verificar_sanidade(maior, caso)


def _assert_log_sem_pii(caso: dict, capsys) -> None:
    """Log não leva conteúdo clínico: nem as lacunas, nem nomes de terceiros."""
    capturado = capsys.readouterr()
    log = capturado.out + capturado.err
    vazamentos = b47._detectar_vazamentos(
        caso, log, ignorar_lacunas=False, ignorar_nomes_de_terceiros=False)
    assert not vazamentos, f"{caso['id']}: PII no log do servidor: {vazamentos}."


# ---------------------------------------------------------------------------
# Canários: provam que os dois caminhos de fato carregam a PII
# ---------------------------------------------------------------------------

@pytest.mark.leak
def test_canario_transcricao_do_audio_traz_a_pii():
    caso = b47._carregar_caso(b47.CASOS[0])
    texto = _ProvedorDoCaso(caso).processar_audio("x.wav")["full_text"]
    assert b47._detectar_vazamentos(caso, texto, ignorar_lacunas=False), (
        "A transcrição falsa não tem a PII do caso: o teste do áudio estaria cego."
    )


@pytest.mark.leak
@pytest.mark.parametrize("caminho", b47.CASOS, ids=b47.IDS_PARAM)
def test_canario_pdf_real_traz_a_pii(caminho, leitor_pdf_real):
    """O texto extraído do PDF gerado tem TODA a PII que a transcrição tem:
    se o gerador ou o extrator perdessem algo, o teste do PDF ficaria cego."""
    caso = b47._carregar_caso(caminho)
    extraido = leitor_pdf_real.extract_text_from_pdf(
        FileStorage(io.BytesIO(_pdf_do_caso(caso)), filename="laudo.pdf"))
    esperados = b47._detectar_vazamentos(caso, caso["transcricao"], ignorar_lacunas=False)
    encontrados = b47._detectar_vazamentos(caso, extraido, ignorar_lacunas=False)
    assert esperados and set(esperados) <= set(encontrados), (
        f"{caso['id']}: o PDF não carrega {sorted(set(esperados) - set(encontrados))}."
    )


# ---------------------------------------------------------------------------
# Teste C — áudio transcrito (bloqueante, ×20)
# ---------------------------------------------------------------------------

@pytest.mark.leak
@pytest.mark.parametrize("caminho", b47.CASOS, ids=b47.IDS_PARAM)
def test_audio_transcrito_nao_vaza_pii(
    caminho, client, auth_headers, ner_desligado, cofre_aberto, llm, pasta_audio,
    monkeypatch, capsys,
):
    import server

    caso = b47._carregar_caso(caminho)
    monkeypatch.setattr(server, "transcription_provider", _ProvedorDoCaso(caso))
    pid, cid = _paciente_e_consulta(caso)
    medico = auth_headers("medico")

    # 1. A extensão envia a gravação em partes e pede a transcrição (B30/B31).
    parte = client.post(f"/api/consultations/{cid}/audio/chunks", headers=medico,
                        content_type="multipart/form-data", data={
                            "recording_id": GRAVACAO, "seq": "1",
                            "audio_file": (_wav_de_silencio(), "parte-1.wav")})
    assert parte.status_code == 202, parte.get_data(as_text=True)[:300]
    transcrita = client.post(f"/api/consultations/{cid}/transcribe", headers=medico,
                             json={"recording_id": GRAVACAO})
    assert transcrita.status_code == 200, transcrita.get_data(as_text=True)[:300]
    transcricao = transcrita.get_json()["transcription"]
    # Volta crua para o médico ler: a PII está no fluxo, o que torna o teste válido.
    assert b47._detectar_vazamentos(caso, transcricao, ignorar_lacunas=False)

    # 2. O popup manda a transcrição para o chat (useAudioRecording.ts).
    chat = client.post("/api/chat", headers=medico, json={
        "message": transcricao, "patient_id": pid, "consultation_id": cid})
    assert chat.status_code == 200, chat.get_data(as_text=True)[:300]

    # 3. Sugestões sobre a janela da consulta (B38) e o SOAP (B40).
    sugestoes = client.post("/api/recommendations", headers=medico, json={
        "patient_id": pid, "consultation_id": cid, "janela_min": 30})
    assert sugestoes.status_code == 200, sugestoes.get_data(as_text=True)[:300]
    assert sugestoes.get_json()["transcricoes_usadas"] == 1
    soap = client.post(f"/api/consultations/{cid}/soap", headers=medico)
    assert soap.status_code == 201, soap.get_data(as_text=True)[:300]

    _assert_sem_vazamento(caso, llm, {"chat", "recomendacoes", "soap"})
    _assert_log_sem_pii(caso, capsys)


# ---------------------------------------------------------------------------
# Teste D — PDF (bloqueante, ×20)
# ---------------------------------------------------------------------------

@pytest.mark.leak
@pytest.mark.parametrize("caminho", b47.CASOS, ids=b47.IDS_PARAM)
def test_pdf_nao_vaza_pii(
    caminho, client, auth_headers, ner_desligado, cofre_aberto, llm, leitor_pdf_real, capsys,
):
    caso = b47._carregar_caso(caminho)
    pid, cid = _paciente_e_consulta(caso)
    medico = auth_headers("medico")

    # 1. O médico anexa o PDF; o texto extraído vai para o chat da consulta.
    enviado = client.post("/api/upload-pdf", headers=medico, content_type="multipart/form-data",
                          data={"pdf": (io.BytesIO(_pdf_do_caso(caso)), "laudo.pdf"),
                                "patient_id": pid, "consultation_id": cid})
    assert enviado.status_code == 200, enviado.get_data(as_text=True)[:300]

    # 2. O SOAP relê o PDF da consulta ("documentos anexados", B40).
    soap = client.post(f"/api/consultations/{cid}/soap", headers=medico)
    assert soap.status_code == 201, soap.get_data(as_text=True)[:300]

    _assert_sem_vazamento(caso, llm, {"chat", "soap"})
    _assert_log_sem_pii(caso, capsys)
