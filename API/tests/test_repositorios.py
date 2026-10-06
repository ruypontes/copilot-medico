"""B20 - repositorios que substituem o backend/patient_db.py e o users_db.json.

Substitui o antigo test_patient_db.py: os mesmos cenarios (paciente,
consultas, historico, extensao, transcricao, posse) agora contra o banco.
"""
import json
import uuid

import pytest
from sqlalchemy import select, text

from models import Paciente
from repositories import (
    ConsultaRepository,
    DadoExtensaoRepository,
    MedicoNaoEncontrado,
    MedicoRepository,
    MensagemRepository,
    PacienteRepository,
    TranscricaoRepository,
    sessao,
)

from conftest import TEST_USER_ID


@pytest.fixture()
def repo(temp_db_file):
    def _repo(cls):
        return cls(sessao.obter_sessao())
    return _repo


# --- pacientes -----------------------------------------------------------

def test_criar_paciente_com_nome_padrao(repo):
    paciente = repo(PacienteRepository).criar()

    assert uuid.UUID(paciente["id"])
    assert paciente["name"] == "Desconhecido"
    assert paciente["doctor_id"] is None


def test_nome_fica_em_pseudonimo_e_nao_em_paciente(repo):
    paciente = repo(PacienteRepository).criar(nome="Maria")

    s = sessao.obter_sessao()
    linha = s.execute(text("SELECT dados_cifrados, algoritmo_cifra FROM pseudonimo")).one()
    assert json.loads(linha.dados_cifrados) == {"nome": "Maria"}
    assert linha.algoritmo_cifra == "none"
    modelo = s.scalar(select(Paciente))
    assert modelo.pseudonimo.startswith("PAC-")
    assert "Maria" not in modelo.pseudonimo
    assert repo(PacienteRepository).obter(paciente["id"])["name"] == "Maria"


def test_criar_paciente_com_medico(repo):
    paciente = repo(PacienteRepository).criar(nome="Ana", medico_id=TEST_USER_ID,
                                              criado_por_id=TEST_USER_ID)

    assert paciente["doctor_id"] == TEST_USER_ID
    assert paciente["created_by"] == TEST_USER_ID


def test_medico_inexistente_e_recusado(repo):
    with pytest.raises(MedicoNaoEncontrado):
        repo(PacienteRepository).criar(medico_id=str(uuid.uuid4()))
    with pytest.raises(MedicoNaoEncontrado):
        repo(PacienteRepository).criar(medico_id="nao-e-uuid")


def test_criador_inexistente_vira_nulo(repo):
    paciente = repo(PacienteRepository).criar(criado_por_id=str(uuid.uuid4()))

    assert paciente["created_by"] is None


@pytest.mark.parametrize("paciente_id", ["nao-existe", "paciente_abc", "", None, str(uuid.uuid4())])
def test_obter_id_invalido_ou_inexistente_devolve_none(repo, paciente_id):
    assert repo(PacienteRepository).obter(paciente_id) is None


def test_listar_filtra_por_medico(repo):
    pacientes = repo(PacienteRepository)
    meu = pacientes.criar(nome="Meu", medico_id=TEST_USER_ID)
    sem_medico = pacientes.criar(nome="Sem medico")

    todos = {p["id"] for p in pacientes.listar()}
    meus = {p["id"] for p in pacientes.listar(medico_id=TEST_USER_ID)}

    assert todos == {meu["id"], sem_medico["id"]}
    assert meus == {meu["id"]}
    assert pacientes.listar(medico_id=str(uuid.uuid4())) == []


# --- consultas e mensagens ---------------------------------------------

def test_criar_e_listar_consultas_mais_antiga_primeiro(repo):
    pid = repo(PacienteRepository).criar()["id"]
    consultas = repo(ConsultaRepository)
    primeira = consultas.criar(pid, "Primeira", data="2026-01-01T10:00:00+00:00")
    segunda = consultas.criar(pid, "Segunda", data="2026-02-01T10:00:00+00:00")

    lista = consultas.listar(pid)

    assert [c["id"] for c in lista] == [primeira, segunda]
    assert set(lista[0]) == {"id", "title", "date", "chat_history"}
    assert lista[0]["title"] == "Primeira"


def test_criar_consulta_para_paciente_inexistente(repo):
    assert repo(ConsultaRepository).criar(str(uuid.uuid4()), "X") is None


def test_historico_no_formato_do_gemini_e_em_ordem(repo):
    pid = repo(PacienteRepository).criar()["id"]
    cid = repo(ConsultaRepository).criar(pid, "C1")
    mensagens = repo(MensagemRepository)

    # Varias mensagens seguidas: no Windows o relogio pode repetir o instante;
    # o repositorio garante ts crescente para nao embaralhar o chat.
    for i in range(20):
        mensagens.adicionar(cid, "user" if i % 2 == 0 else "model", f"m{i}")

    historico = mensagens.historico(cid)
    assert [m["parts"][0]["text"] for m in historico] == [f"m{i}" for i in range(20)]
    assert historico[0] == {"role": "user", "parts": [{"text": "m0"}], "timestamp": historico[0]["timestamp"]}
    assert repo(ConsultaRepository).listar(pid)[0]["chat_history"] == historico


def test_mensagem_em_consulta_inexistente_e_ignorada(repo):
    assert repo(MensagemRepository).adicionar(str(uuid.uuid4()), "user", "x") is None


def test_historico_inicial_preserva_ordem(repo):
    pid = repo(PacienteRepository).criar()["id"]
    historico = [
        {"role": "model", "parts": [{"text": "cabecalho"}]},
        {"role": "user", "parts": [{"text": "pergunta antiga"}], "timestamp": "2020-01-01T00:00:00"},
        {"role": "model", "parts": [{"text": "resposta antiga"}]},
    ]
    cid = repo(ConsultaRepository).criar(pid, "Com importacao", historico_inicial=historico)
    repo(MensagemRepository).adicionar(cid, "user", "nova")

    textos = [m["parts"][0]["text"] for m in repo(MensagemRepository).historico(cid)]
    assert textos == ["cabecalho", "pergunta antiga", "resposta antiga", "nova"]


def test_consulta_pertence_ao_paciente(repo):
    pacientes = repo(PacienteRepository)
    pid, outro = pacientes.criar()["id"], pacientes.criar()["id"]
    cid = repo(ConsultaRepository).criar(pid, "C1")

    consultas = repo(ConsultaRepository)
    assert consultas.pertence_ao_paciente(pid, cid) is True
    assert consultas.pertence_ao_paciente(outro, cid) is False
    assert consultas.pertence_ao_paciente(pid, None) is False
    assert consultas.pertence_ao_paciente(pid, "nao-e-uuid") is False


# --- extensao e transcricao --------------------------------------------

def test_dados_da_extensao_mais_recente_primeiro(repo):
    pid = repo(PacienteRepository).criar()["id"]
    cid = repo(ConsultaRepository).criar(pid, "C1")
    dados = repo(DadoExtensaoRepository)
    antigo = dados.adicionar(pid, {"peso": "70"}, criado_em="2026-01-01T10:00:00")
    novo = dados.adicionar(pid, [{"role": "Anamnese", "text": "dor"}], consulta_id=cid,
                           url_origem="https://pep.example/atendimento")

    itens = dados.listar(pid)

    assert [i["id"] for i in itens] == [novo["id"], antigo["id"]]
    assert itens[0]["consultation_id"] == cid
    assert itens[0]["source"] == "extension"
    assert itens[0]["type"] == "extracted_data"
    assert itens[0]["source_url"] == "https://pep.example/atendimento"
    assert itens[1]["created_at"] == "2026-01-01T10:00:00+00:00"
    assert itens[1]["content"] == {"peso": "70"}


def test_transcricao_mantem_formato_do_log(repo):
    pid = repo(PacienteRepository).criar()["id"]
    turnos = [{"speaker": "medico", "text": "Bom dia", "start": 0, "end": 2}]

    entrada = repo(TranscricaoRepository).adicionar(
        pid, None, texto="Bom dia", duracao_s=125, turnos=turnos,
        metadados_audio={"persisted": False, "filename": "a.wav"},
    )

    assert entrada["duration"] == "2:05"
    assert entrada["dialogue"] == turnos
    assert entrada["source"] == "extension"
    assert entrada["type"] == "transcription"
    assert entrada["audio"]["filename"] == "a.wav"
    assert repo(TranscricaoRepository).listar(pid)[0]["id"] == entrada["id"]


def test_registros_de_paciente_inexistente_nao_sao_gravados(repo):
    fantasma = str(uuid.uuid4())
    assert repo(DadoExtensaoRepository).adicionar(fantasma, {"x": 1}) is None
    assert repo(TranscricaoRepository).adicionar(fantasma, None, texto="x", duracao_s=1) is None


# --- medicos / usuarios --------------------------------------------------

def test_usuario_no_formato_do_auth_service(repo):
    medicos = repo(MedicoRepository)
    criado = medicos.criar({
        "email": "dra@example.com", "name": "Dra", "password_hash": "h",
        "profiles": ["medico"], "active": False, "crm": "123", "specialty": "Clinica",
        "approval_status": "pending", "approved_by": None, "rejected_by": None,
    })

    lido = medicos.obter_por_email("dra@example.com")
    assert lido == criado
    assert lido["approval_status"] == "pending"
    assert lido["profiles"] == ["medico"]
    assert lido["active"] is False


def test_aprovacao_referencia_quem_aprovou(repo):
    medicos = repo(MedicoRepository)
    medico = medicos.criar({"email": "m@example.com", "name": "M", "password_hash": "h",
                            "profiles": ["medico"], "approval_status": "pending"})

    medico.update(approval_status="approved", active=True,
                  approved_at="2026-10-05T12:00:00+00:00", approved_by=TEST_USER_ID)
    atualizado = medicos.atualizar(medico)

    assert atualizado["approval_status"] == "approved"
    assert atualizado["approved_by"] == TEST_USER_ID


def test_bootstrap_cria_admin_quando_nao_ha_usuarios(repo, monkeypatch):
    from backend import auth_service

    sessao.obter_sessao().execute(text("DELETE FROM medico"))
    sessao.obter_sessao().commit()
    monkeypatch.setattr(auth_service.settings, "auth_bootstrap_email", "admin@example.com")
    monkeypatch.setattr(auth_service.settings, "auth_bootstrap_password", "SenhaForte123!")

    usuario = auth_service.authenticate_user("admin@example.com", "SenhaForte123!")

    assert usuario is not None
    assert usuario["profiles"] == ["administrador"]
    assert repo(MedicoRepository).contar() == 1


def test_fluxo_de_cadastro_e_aprovacao_de_medico(repo):
    from backend import auth_service

    pedido = auth_service.create_doctor_registration(
        name="Dr. Pedro", email="pedro@example.com", password="SenhaForte123!", crm="CRM-1",
    )
    assert [d["id"] for d in auth_service.list_doctor_requests("pending")] == [pedido["id"]]

    aprovado = auth_service.approve_doctor_request(pedido["id"], TEST_USER_ID)

    assert aprovado["approval_status"] == "approved"
    assert aprovado["approved_by"] == TEST_USER_ID
    assert auth_service.authenticate_user("pedro@example.com", "SenhaForte123!")["active"] is True
    with pytest.raises(ValueError):
        auth_service.create_doctor_registration(
            name="Outro", email="pedro@example.com", password="x",
        )
