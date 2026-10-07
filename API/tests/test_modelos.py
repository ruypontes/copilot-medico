"""B19 - regras do esquema: chaves estrangeiras, cascata, CHECK e defaults.

Usa SQLite com o esquema criado pelos proprios modelos; test_migracoes.py
garante que a migracao produz exatamente esse esquema.
"""
import json
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from models import (
    ALGORITMO_SEM_CIFRA,
    Base,
    Consentimento,
    Consulta,
    DadoExtensao,
    Medico,
    Mensagem,
    Paciente,
    PapelMensagem,
    Pseudonimo,
    StatusAprovacao,
    TipoConsentimento,
    Transcricao,
    create_db_engine,
    make_session_factory,
)


@pytest.fixture()
def session(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'modelos.db').as_posix()}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def _medico(session, email="medica@example.com", **kwargs):
    medico = Medico(
        email=email, senha_hash="scrypt:hash", nome="Dra. Ana", perfis=["medico"],
        status_aprovacao=StatusAprovacao.APROVADO, **kwargs,
    )
    session.add(medico)
    session.flush()
    return medico


def _paciente(session, medico, pseudonimo="PAC-0001", nome="Maria"):
    paciente = Paciente(medico_id=medico.id, pseudonimo=pseudonimo)
    paciente.dados_identificaveis = Pseudonimo(
        dados_cifrados=json.dumps({"nome": nome}).encode("utf-8")
    )
    session.add(paciente)
    session.flush()
    return paciente


def _consulta(session, paciente):
    consulta = Consulta(paciente_id=paciente.id, medico_id=paciente.medico_id, titulo="Retorno")
    session.add(consulta)
    session.flush()
    return consulta


# --- medico -------------------------------------------------------------

def test_medico_defaults(session):
    medico = _medico(session)

    assert isinstance(medico.id, uuid.UUID)
    assert medico.ativo is True
    assert medico.criado_em is not None


def test_administrador_sem_crm_e_sem_aprovacao(session):
    admin = Medico(email="admin@example.com", senha_hash="x", nome="Admin", perfis=["administrador"])
    session.add(admin)
    session.flush()

    assert admin.crm is None
    assert admin.status_aprovacao is None


def test_email_de_medico_e_unico(session):
    _medico(session, email="dup@example.com")
    with pytest.raises(IntegrityError):
        _medico(session, email="dup@example.com")


def test_status_aprovacao_grava_o_valor_usado_pelo_auth_service(session):
    medico = _medico(session)

    gravado = session.execute(
        text("SELECT status_aprovacao FROM medico WHERE email = :e"), {"e": medico.email}
    ).scalar_one()

    assert gravado == "approved"


# --- paciente e pseudonimo ---------------------------------------------

def test_paciente_nao_tem_coluna_de_nome(session):
    # US015-CA004: o nome fica so em pseudonimo.
    assert "nome" not in Paciente.__table__.columns


def test_nome_fica_em_pseudonimo_ainda_sem_cifra(session):
    paciente = _paciente(session, _medico(session), nome="Maria")

    dados = paciente.dados_identificaveis
    assert dados.algoritmo_cifra == ALGORITMO_SEM_CIFRA
    assert json.loads(dados.dados_cifrados) == {"nome": "Maria"}


def test_paciente_sem_medico_e_permitido(session):
    # Admin pode criar paciente sem medico responsavel (comportamento atual).
    session.add(Paciente(pseudonimo="PAC-SEM-MEDICO"))
    session.flush()


def test_nao_apaga_medico_que_ainda_tem_pacientes(session):
    medico = _medico(session)
    _paciente(session, medico)

    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM medico WHERE id = :id"), {"id": medico.id.hex})


# --- consulta e dependentes --------------------------------------------

def test_apagar_consulta_apaga_mensagens_e_consentimento(session):
    consulta = _consulta(session, _paciente(session, _medico(session)))
    session.add_all([
        Mensagem(consulta_id=consulta.id, papel=PapelMensagem.USUARIO, conteudo_pseudonimizado="oi"),
        Mensagem(consulta_id=consulta.id, papel=PapelMensagem.MODELO, conteudo_pseudonimizado="ola"),
        Consentimento(consulta_id=consulta.id, tipo=TipoConsentimento.VERBAL, versao_texto="v1"),
    ])
    session.flush()

    session.execute(text("DELETE FROM consulta WHERE id = :id"), {"id": consulta.id.hex})

    assert session.execute(text("SELECT count(*) FROM mensagem")).scalar_one() == 0
    assert session.execute(text("SELECT count(*) FROM consentimento")).scalar_one() == 0


def test_registros_do_paciente_sobrevivem_a_consulta_apagada(session):
    paciente = _paciente(session, _medico(session))
    consulta = _consulta(session, paciente)
    session.add_all([
        Transcricao(paciente_id=paciente.id, consulta_id=consulta.id, texto="relato"),
        DadoExtensao(paciente_id=paciente.id, consulta_id=consulta.id, conteudo={"peso": "70"}),
    ])
    session.flush()

    session.execute(text("DELETE FROM consulta WHERE id = :id"), {"id": consulta.id.hex})

    consultas_ids = session.execute(
        text("SELECT consulta_id FROM transcricao UNION ALL SELECT consulta_id FROM dado_extensao")
    ).scalars().all()
    assert consultas_ids == [None, None]


def test_apagar_paciente_apaga_tudo_dele(session):
    paciente = _paciente(session, _medico(session))
    consulta = _consulta(session, paciente)
    session.add(Mensagem(consulta_id=consulta.id, papel=PapelMensagem.USUARIO, conteudo_pseudonimizado="x"))
    session.add(Transcricao(paciente_id=paciente.id, texto="relato"))
    session.flush()

    session.execute(text("DELETE FROM paciente WHERE id = :id"), {"id": paciente.id.hex})

    for tabela in ("pseudonimo", "consulta", "mensagem", "transcricao"):
        assert session.execute(text(f"SELECT count(*) FROM {tabela}")).scalar_one() == 0, tabela


def test_mensagem_exige_consulta_existente(session):
    session.add(Mensagem(consulta_id=uuid.uuid4(), papel=PapelMensagem.USUARIO, conteudo_pseudonimizado="x"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_check_rejeita_papel_invalido_gravado_direto_no_banco(session):
    consulta = _consulta(session, _paciente(session, _medico(session)))

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO mensagem (id, consulta_id, papel, conteudo_pseudonimizado, ts) "
                "VALUES (:id, :c, 'sistema', 'x', CURRENT_TIMESTAMP)"
            ),
            {"id": uuid.uuid4().hex, "c": consulta.id.hex},
        )


def test_json_preserva_formatos_da_extensao(session):
    paciente = _paciente(session, _medico(session))
    formatos = [
        [{"role": "Anamnese", "text": "dor"}],
        {"peso": "70", "alergias": ["dipirona"]},
        "texto livre",
    ]
    session.add_all(DadoExtensao(paciente_id=paciente.id, conteudo=c) for c in formatos)
    session.commit()

    lidos = session.execute(select(DadoExtensao.conteudo)).scalars().all()
    assert sorted(map(json.dumps, lidos)) == sorted(map(json.dumps, formatos))
