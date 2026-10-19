"""B39 - esquema SoapV1 e tabela documento_soap (US018 / ADR-05)."""
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.soap import Confianca, SoapInvalido, SoapV1, response_schema, validar_soap
from repositories import (
    ConsultaRepository,
    DocumentoSoapRepository,
    PacienteRepository,
    TransicaoInvalida,
    sessao,
)

CASOS = sorted((Path(__file__).resolve().parents[1] / "eval" / "cases").glob("caso-*.json"))


def _soap(**extra):
    base = {
        "subjetivo": "Cefaleia em aperto ha 3 dias.",
        "objetivo": "PA 120/80 mmHg, exame neurologico sem alteracoes.",
        "avaliacao": "Cefaleia tensional.",
        "plano": "Dipirona se dor; retorno em 7 dias.",
        "hipoteses": [{"descricao": "Cefaleia tensional", "cid10": "G44.2", "confianca": "alta"}],
        "alertas": ["Retornar se febre ou rigidez de nuca"],
        "pendencias": ["Fundoscopia nao realizada"],
    }
    base.update(extra)
    return base


# --- esquema ----------------------------------------------------------------------

def test_soap_valido():
    soap = validar_soap(_soap())

    assert isinstance(soap, SoapV1)
    assert soap.hipoteses[0].confianca is Confianca.ALTA
    assert soap.model_dump(mode="json")["hipoteses"][0]["confianca"] == "alta"


def test_aceita_texto_json():
    assert validar_soap(json.dumps(_soap())).avaliacao == "Cefaleia tensional."


def test_listas_sao_opcionais():
    soap = validar_soap({k: v for k, v in _soap().items() if k in ("subjetivo", "objetivo", "avaliacao", "plano")})

    assert soap.hipoteses == [] and soap.alertas == [] and soap.pendencias == []


def test_normaliza_cid10_confianca_e_espacos():
    soap = validar_soap(_soap(
        subjetivo="  dor  ",
        hipoteses=[
            {"descricao": "Cefaleia", "cid10": "g442", "confianca": "Média"},
            {"descricao": "Hipertensao", "cid10": "i10", "confianca": "baixa"},
            {"descricao": "Sem codigo definido", "cid10": "", "confianca": "baixa"},
        ],
    ))

    assert soap.subjetivo == "dor"
    assert [h.cid10 for h in soap.hipoteses] == ["G44.2", "I10", None]
    assert soap.hipoteses[0].confianca is Confianca.MEDIA


@pytest.mark.parametrize("entrada, campo_com_erro", [
    ("{nao e json", "JSON malformado"),
    ("[]", "deve ser um objeto"),
    ([], "deve ser um objeto"),
    ({"subjetivo": "a", "objetivo": "b", "avaliacao": "c"}, "plano: obrigatorio"),
    (_soap(plano="   "), "plano: nao pode ser vazio"),
    (_soap(diagnostico="x"), "diagnostico: campo nao faz parte do SoapV1"),
    (_soap(avaliacao=123), "avaliacao: deve ser texto"),
    (_soap(alertas="tosse"), "alertas: deve ser uma lista"),
    (_soap(pendencias=["ok", ""]), "pendencias"),
    (_soap(hipoteses=[{"descricao": "Cefaleia", "confianca": "85%"}]), "hipoteses.0.confianca: use um de: baixa, media, alta"),
    (_soap(hipoteses=[{"descricao": "Cefaleia", "cid10": "XYZ", "confianca": "alta"}]), "hipoteses.0.cid10: cid10 invalido"),
    (_soap(hipoteses=[{"descricao": "Cefaleia"}]), "hipoteses.0.confianca: obrigatorio"),
    (_soap(hipoteses=[{"descricao": "Cefaleia", "confianca": "alta", "probabilidade": 0.8}]), "hipoteses.0.probabilidade"),
    (_soap(hipoteses=[{"descricao": "x", "confianca": "alta"}] * 11), "hipoteses: itens demais"),
])
def test_rejeita_json_invalido(entrada, campo_com_erro):
    with pytest.raises(SoapInvalido) as erro:
        validar_soap(entrada)

    assert any(campo_com_erro in e for e in erro.value.erros), erro.value.erros


def test_erro_lista_todos_os_problemas():
    with pytest.raises(SoapInvalido) as erro:
        validar_soap({"subjetivo": "", "extra": 1})

    assert len(erro.value.erros) >= 4  # subjetivo vazio, 3 secoes faltando, campo extra


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c.stem)
def test_gabaritos_do_b45_seguem_o_soapv1(caso):
    dados = json.loads(caso.read_text(encoding="utf-8"))
    soap = validar_soap({
        **dados["gabarito_soap"],
        "pendencias": dados["pendencias"],
        "hipoteses": [{"descricao": "hipotese do gabarito", "cid10": cid, "confianca": "media"}
                      for cid in dados["cid10_esperado"]],
    })

    assert [h.cid10 for h in soap.hipoteses] == dados["cid10_esperado"]


def test_response_schema_para_o_gemini():
    schema = response_schema()

    assert set(schema["required"]) == {"subjetivo", "objetivo", "avaliacao", "plano", "hipoteses", "alertas", "pendencias"}
    hipotese = schema["properties"]["hipoteses"]["items"]
    assert hipotese["properties"]["confianca"]["enum"] == ["baixa", "media", "alta"]
    # Subconjunto de OpenAPI aceito pelo Gemini: nada de $ref/$defs/additionalProperties.
    serializado = json.dumps(schema)
    assert "$ref" not in serializado and "$defs" not in serializado and "additionalProperties" not in serializado


# --- tabela documento_soap ---------------------------------------------------------

@pytest.fixture()
def repo_e_consulta(temp_db_file):
    s = sessao.obter_sessao()
    pid = PacienteRepository(s).criar(nome="Paciente")["id"]
    return DocumentoSoapRepository(s), ConsultaRepository(s).criar(pid, "Consulta")


def test_criar_grava_versao_ia_valida_e_rastreavel(repo_e_consulta):
    repo, cid = repo_e_consulta

    doc = repo.criar(cid, _soap(hipoteses=[{"descricao": "Cefaleia", "cid10": "g442", "confianca": "Média"}]),
                     prompt_id="soap", prompt_versao="1")

    assert doc["status"] == "gerado" and doc["schema_version"] == "SoapV1"
    assert doc["prompt"] == {"id": "soap", "versao": "1"}
    assert doc["versao_ia"]["hipoteses"][0] == {"descricao": "Cefaleia", "cid10": "G44.2", "confianca": "media"}
    assert doc["versao_medico"] is None and doc["atual"] == doc["versao_ia"]
    assert repo.listar_da_consulta(cid)[0]["id"] == doc["id"]


def test_json_invalido_nao_chega_ao_banco(repo_e_consulta):
    repo, cid = repo_e_consulta

    with pytest.raises(SoapInvalido):
        repo.criar(cid, {"subjetivo": "so isso"})

    assert sessao.obter_sessao().execute(text("select count(*) from documento_soap")).scalar_one() == 0


def test_consulta_inexistente(repo_e_consulta):
    repo, _cid = repo_e_consulta

    assert repo.criar("00000000-0000-4000-8000-000000000999", _soap()) is None


def test_edicao_do_medico_preserva_a_versao_da_ia(repo_e_consulta):
    repo, cid = repo_e_consulta
    doc = repo.criar(cid, _soap())

    editado = repo.salvar_edicao(doc["id"], _soap(plano="Plano revisado pelo medico."))

    assert editado["status"] == "editado"
    assert editado["versao_ia"]["plano"] == "Dipirona se dor; retorno em 7 dias."
    assert editado["versao_medico"]["plano"] == "Plano revisado pelo medico."
    assert editado["atual"]["plano"] == "Plano revisado pelo medico."
    assert editado["updated_at"] is not None

    with pytest.raises(SoapInvalido):
        repo.salvar_edicao(doc["id"], _soap(plano=""))
    assert repo.obter(doc["id"])["versao_medico"]["plano"] == "Plano revisado pelo medico."


def test_aprovar_e_bloquear_edicao(repo_e_consulta):
    repo, cid = repo_e_consulta
    doc = repo.criar(cid, _soap())

    aprovado = repo.aprovar(doc["id"])

    assert aprovado["status"] == "aprovado" and aprovado["approved_at"] is not None
    assert repo.aprovar(doc["id"])["approved_at"] == aprovado["approved_at"]  # idempotente
    with pytest.raises(TransicaoInvalida):
        repo.salvar_edicao(doc["id"], _soap())


@pytest.mark.parametrize("documento_id", ["nao-e-uuid", "00000000-0000-4000-8000-000000000999"])
def test_documento_inexistente(repo_e_consulta, documento_id):
    repo, _cid = repo_e_consulta

    assert repo.obter(documento_id) is None
    assert repo.salvar_edicao(documento_id, _soap()) is None
    assert repo.aprovar(documento_id) is None
