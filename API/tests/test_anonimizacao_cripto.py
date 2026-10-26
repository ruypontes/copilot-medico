"""Cifra do mapa de pseudonimos e persistencia (B26 / US016-CA002, ADR-03).

O criterio de aceite do B26 e o teste de ida e volta: anonimizar, persistir
cifrado, recarregar e reidratar devolvendo o texto original.
"""
from __future__ import annotations

import json

import pytest

from backend.anonimizacao import MapaAnonimizacao, anonimizar
from backend.anonimizacao import cofres, cripto
from repositories import MapaAnonimizacaoRepository, sessao

from conftest import TEST_USER_ID

SENHA = "senha-do-medico-123"


# ---------------------------------------------------------------------------
# Primitivas de cifra
# ---------------------------------------------------------------------------

def test_cofre_cifra_e_decifra_json():
    cofre, _, _ = cripto.criar_cofre(SENHA)
    dados = {"[PACIENTE_1]": "Maria Souza", "[CPF_1]": "529.982.247-25"}

    blob = cofre.cifrar_json(dados)

    assert cofre.decifrar_json(blob) == dados


def test_dado_sensivel_nao_aparece_no_blob():
    """Se o nome aparecesse no blob, a cifra seria decorativa."""
    cofre, _, _ = cripto.criar_cofre(SENHA)

    blob = cofre.cifrar_json({"[PACIENTE_1]": "Maria Souza"})

    assert b"Maria" not in blob
    assert b"PACIENTE" not in blob


def test_mesma_entrada_gera_blobs_diferentes():
    """Nonce aleatorio: dois ciframentos iguais nao podem ser identicos,
    senao da para inferir repeticao de conteudo."""
    cofre, _, _ = cripto.criar_cofre(SENHA)
    dados = {"[CPF_1]": "529.982.247-25"}

    assert cofre.cifrar_json(dados) != cofre.cifrar_json(dados)


def test_senha_correta_reabre_o_cofre():
    cofre, dek_cifrada, salt = cripto.criar_cofre(SENHA)
    blob = cofre.cifrar_json({"[CPF_1]": "529.982.247-25"})

    reaberto = cripto.abrir_cofre(SENHA, dek_cifrada, salt)

    assert reaberto.decifrar_json(blob) == {"[CPF_1]": "529.982.247-25"}


def test_senha_errada_nao_abre_o_cofre():
    _, dek_cifrada, salt = cripto.criar_cofre(SENHA)

    with pytest.raises(cripto.FalhaAoDecifrar):
        cripto.abrir_cofre("senha-errada", dek_cifrada, salt)


def test_blob_adulterado_e_rejeitado():
    """AES-GCM autentica: alterar um bit tem de falhar, nao devolver lixo."""
    cofre, _, _ = cripto.criar_cofre(SENHA)
    blob = bytearray(cofre.cifrar_json({"[CPF_1]": "529.982.247-25"}))
    blob[-1] ^= 0x01

    with pytest.raises(cripto.FalhaAoDecifrar):
        cofre.decifrar_json(bytes(blob))


def test_salt_diferente_por_cofre():
    """Salt fixo permitiria rainbow table sobre as senhas dos medicos."""
    _, _, salt_um = cripto.criar_cofre(SENHA)
    _, _, salt_dois = cripto.criar_cofre(SENHA)

    assert salt_um != salt_dois


def test_troca_de_senha_nao_recifra_os_dados():
    """E o ganho do envelope: so a DEK e reembrulhada."""
    cofre, dek_cifrada, salt = cripto.criar_cofre(SENHA)
    blob = cofre.cifrar_json({"[PACIENTE_1]": "Maria Souza"})

    nova_dek, novo_salt = cripto.reembrulhar(cofre, "senha-nova-456")
    com_senha_nova = cripto.abrir_cofre("senha-nova-456", nova_dek, novo_salt)

    # O MESMO blob, nao recifrado, continua legivel.
    assert com_senha_nova.decifrar_json(blob) == {"[PACIENTE_1]": "Maria Souza"}
    # E a senha antiga deixou de abrir.
    with pytest.raises(cripto.FalhaAoDecifrar):
        cripto.abrir_cofre(SENHA, nova_dek, novo_salt)


def test_cofre_sem_material_de_chave_falha_claramente():
    with pytest.raises(cripto.FalhaAoDecifrar):
        cripto.abrir_cofre(SENHA, b"", b"")


# ---------------------------------------------------------------------------
# Registro de cofres de sessao
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _limpa_cofres():
    cofres.limpar()
    yield
    cofres.limpar()


def test_cofre_guardado_e_recuperado_pela_sessao():
    cofre, _, _ = cripto.criar_cofre(SENHA)

    cofres.guardar("token-abc", cofre)

    assert cofres.obter("token-abc") is cofre


def test_logout_descarta_a_chave_da_memoria():
    cofre, _, _ = cripto.criar_cofre(SENHA)
    cofres.guardar("token-abc", cofre)

    cofres.descartar("token-abc")

    assert cofres.obter("token-abc") is None
    assert cofres.total_aberto() == 0


def test_sessao_desconhecida_devolve_none():
    assert cofres.obter("nao-existe") is None
    assert cofres.obter(None) is None


# ---------------------------------------------------------------------------
# Persistencia do mapa por consulta
# ---------------------------------------------------------------------------

@pytest.fixture()
def consulta_id(temp_db_file):
    """Cria paciente e consulta reais para ter FK valida."""
    from repositories import ConsultaRepository, PacienteRepository

    paciente = PacienteRepository(sessao.obter_sessao()).criar(
        nome="Maria Souza", medico_id=TEST_USER_ID
    )
    consulta = ConsultaRepository(sessao.obter_sessao()).criar(
        paciente["id"], "Consulta de teste"
    )
    return consulta["id"] if isinstance(consulta, dict) else consulta


@pytest.fixture()
def repo(temp_db_file):
    return MapaAnonimizacaoRepository(sessao.obter_sessao())


def test_mapa_salvo_volta_identico(repo, consulta_id):
    cofre, _, _ = cripto.criar_cofre(SENHA)
    mapa = MapaAnonimizacao.de_dicionario(
        {"[PACIENTE_1]": "Maria Souza", "[CPF_1]": "529.982.247-25"}
    )

    assert repo.salvar(consulta_id, mapa, cofre) is True
    recarregado = repo.carregar(consulta_id, cofre)

    assert recarregado.para_dicionario() == mapa.para_dicionario()


def test_mapa_fica_cifrado_no_banco(repo, consulta_id):
    """Le a coluna crua: o nome nao pode estar legivel."""
    from sqlalchemy import text

    cofre, _, _ = cripto.criar_cofre(SENHA)
    repo.salvar(consulta_id, MapaAnonimizacao.de_dicionario({"[PACIENTE_1]": "Maria Souza"}), cofre)

    linha = sessao.obter_sessao().execute(
        text("SELECT dados_cifrados, algoritmo_cifra FROM mapa_anonimizacao")
    ).one()

    assert b"Maria" not in bytes(linha[0])
    assert linha[1] == cripto.ALGORITMO


def test_sem_cofre_o_mapa_nao_e_gravado_em_texto(repo, consulta_id):
    """Preferimos perder a estabilidade dos tokens a gravar PII legivel."""
    mapa = MapaAnonimizacao.de_dicionario({"[PACIENTE_1]": "Maria Souza"})

    assert repo.salvar(consulta_id, mapa, cofre=None) is False
    assert len(repo.carregar(consulta_id, cofre=None)) == 0


def test_cofre_errado_devolve_mapa_vazio_sem_estourar(repo, consulta_id):
    cofre, _, _ = cripto.criar_cofre(SENHA)
    repo.salvar(consulta_id, MapaAnonimizacao.de_dicionario({"[CPF_1]": "529.982.247-25"}), cofre)

    outro_cofre, _, _ = cripto.criar_cofre("outra-senha")

    assert len(repo.carregar(consulta_id, outro_cofre)) == 0


def test_linha_legada_sem_cifra_ainda_e_lida(repo, consulta_id):
    """Compatibilidade com o algoritmo "none" que o B19 deixou previsto."""
    from models import MapaAnonimizacaoConsulta
    from repositories.base import parse_uuid

    s = sessao.obter_sessao()
    s.add(MapaAnonimizacaoConsulta(
        consulta_id=parse_uuid(consulta_id),
        dados_cifrados=json.dumps({"[CPF_1]": "529.982.247-25"}).encode("utf-8"),
        algoritmo_cifra=cripto.ALGORITMO_SEM_CIFRA,
    ))
    s.commit()

    mapa = repo.carregar(consulta_id, cofre=None)

    assert mapa.valores["[CPF_1]"] == "529.982.247-25"


def test_salvar_de_novo_atualiza_a_mesma_linha(repo, consulta_id):
    cofre, _, _ = cripto.criar_cofre(SENHA)
    repo.salvar(consulta_id, MapaAnonimizacao.de_dicionario({"[CPF_1]": "111"}), cofre)
    repo.salvar(consulta_id, MapaAnonimizacao.de_dicionario({"[CPF_1]": "222"}), cofre)

    from sqlalchemy import text
    total = sessao.obter_sessao().execute(
        text("SELECT COUNT(*) FROM mapa_anonimizacao")
    ).scalar()

    assert total == 1
    assert repo.carregar(consulta_id, cofre).valores["[CPF_1]"] == "222"


# ---------------------------------------------------------------------------
# Ida e volta completa (criterio de aceite do B26)
# ---------------------------------------------------------------------------

def test_ida_e_volta_completa_com_persistencia(repo, consulta_id):
    """Anonimiza -> persiste cifrado -> recarrega -> reidrata a resposta."""
    cofre, dek_cifrada, salt = cripto.criar_cofre(SENHA)
    texto = "Maria Souza, CPF 529.982.247-25, telefone (81) 99876-5432."

    # 1. Anonimiza e persiste o mapa cifrado.
    resultado = anonimizar(texto, nomes_conhecidos=["Maria Souza"], nlp=lambda t: type(
        "D", (), {"ents": []})())
    repo.salvar(consulta_id, resultado.mapa, cofre)

    assert "Maria Souza" not in resultado.texto
    assert "529.982.247-25" not in resultado.texto

    # 2. Nova sessao: medico faz login de novo, cofre reaberto pela senha.
    sessao.encerrar_sessao()
    cofre_reaberto = cripto.abrir_cofre(SENHA, dek_cifrada, salt)
    repo_novo = MapaAnonimizacaoRepository(sessao.obter_sessao())
    mapa_recarregado = repo_novo.carregar(consulta_id, cofre_reaberto)

    # 3. A resposta do modelo, cheia de tokens, volta legivel na exibicao.
    resposta_do_modelo = (
        "Oriente [PACIENTE_1] a confirmar o CPF [CPF_1] "
        "e retorne no telefone [TELEFONE_1]."
    )
    exibido = mapa_recarregado.reidratar(resposta_do_modelo)

    assert "Maria Souza" in exibido
    assert "529.982.247-25" in exibido
    assert "(81) 99876-5432" in exibido
    # E o texto original e reconstruido exatamente.
    assert mapa_recarregado.reidratar(resultado.texto) == texto


# ---------------------------------------------------------------------------
# Tabela `pseudonimo` cifrada (B26, texto literal da tarefa)
# ---------------------------------------------------------------------------

def test_nome_do_paciente_fica_cifrado_no_banco(temp_db_file):
    """Com cofre aberto, `pseudonimo.dados_cifrados` nao pode ter o nome."""
    from sqlalchemy import text

    from repositories import PacienteRepository

    cofre, _, _ = cripto.criar_cofre(SENHA)
    repo = PacienteRepository(sessao.obter_sessao(), cofre)
    repo.criar(nome="Maria Souza", medico_id=TEST_USER_ID)

    linha = sessao.obter_sessao().execute(
        text("SELECT dados_cifrados, algoritmo_cifra FROM pseudonimo")
    ).one()

    assert b"Maria" not in bytes(linha[0])
    assert linha[1] == cripto.ALGORITMO


def test_nome_volta_legivel_com_o_mesmo_cofre(temp_db_file):
    from repositories import PacienteRepository

    cofre, dek_cifrada, salt = cripto.criar_cofre(SENHA)
    criado = PacienteRepository(sessao.obter_sessao(), cofre).criar(
        nome="Maria Souza", medico_id=TEST_USER_ID
    )

    # Simula novo login: cofre reconstruido a partir da senha.
    reaberto = cripto.abrir_cofre(SENHA, dek_cifrada, salt)
    lido = PacienteRepository(sessao.obter_sessao(), reaberto).obter(criado["id"])

    assert lido["name"] == "Maria Souza"


def test_criar_com_cofre_devolve_o_nome_legivel(temp_db_file):
    """A resposta do POST /api/patients sai daqui: com o pseudonimo, a extensao
    mostrava e guardava "PAC-..." logo depois de criar o paciente (achado do B56)."""
    from repositories import PacienteRepository

    cofre, _, _ = cripto.criar_cofre(SENHA)
    criado = PacienteRepository(sessao.obter_sessao(), cofre).criar(
        nome="Maria Souza", medico_id=TEST_USER_ID
    )

    assert criado["name"] == "Maria Souza"


def test_sem_cofre_o_nome_cifrado_vira_pseudonimo(temp_db_file):
    """Degrada para o pseudonimo em vez de mentir "Desconhecido"."""
    from repositories import PacienteRepository

    cofre, _, _ = cripto.criar_cofre(SENHA)
    criado = PacienteRepository(sessao.obter_sessao(), cofre).criar(
        nome="Maria Souza", medico_id=TEST_USER_ID
    )

    lido = PacienteRepository(sessao.obter_sessao(), None).obter(criado["id"])

    assert lido["name"] != "Maria Souza"
    assert lido["name"].startswith("PAC-")


def test_paciente_legado_sem_cifra_continua_legivel(temp_db_file):
    """Linhas gravadas pelo B19 ("none") nao podem quebrar apos o B26."""
    from repositories import PacienteRepository

    criado = PacienteRepository(sessao.obter_sessao(), None).criar(
        nome="Joao Legado", medico_id=TEST_USER_ID
    )

    cofre, _, _ = cripto.criar_cofre(SENHA)
    lido = PacienteRepository(sessao.obter_sessao(), cofre).obter(criado["id"])

    assert lido["name"] == "Joao Legado"
