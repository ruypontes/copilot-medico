"""B40 - script de avaliacao do gerador de SOAP nos 20 casos do B45."""
import json
import sys
from pathlib import Path

from backend.llm import LlmError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import avaliar_soap  # noqa: E402

SOAP = {
    "subjetivo": "Cefaleia.", "objetivo": "PA 120/80 mmHg.", "avaliacao": "Cefaleia tensional.",
    "plano": "Dipirona se dor.",
    "hipoteses": [{"descricao": "Cefaleia tensional", "cid10": "G44.2", "confianca": "alta"}],
    "alertas": [], "pendencias": [],
}


def _modelo(*respostas):
    fila = list(respostas)
    chamadas = []

    def chamar(instrucao, conteudo, schema=None):
        chamadas.append(conteudo)
        resposta = fila.pop(0) if fila else SOAP
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if isinstance(resposta, str) else json.dumps(resposta)

    chamar.chamadas = chamadas
    return chamar


def _rodar(tmp_path, modelo, *args):
    saida = tmp_path / "rel.json"
    codigo = avaliar_soap.main(["--intervalo", "0", "--espera", "0", "--saida", str(saida), *args],
                               chamar_modelo=modelo)
    return codigo, json.loads(saida.read_text(encoding="utf-8"))


def test_vinte_casos_validos_saem_com_codigo_zero(tmp_path, capsys):
    codigo, relatorio = _rodar(tmp_path, _modelo())

    assert codigo == 0
    assert len(relatorio["resultados"]) == 20 and all(r["valido"] for r in relatorio["resultados"])
    assert relatorio["prompt"] == {"id": "soap", "versao": "1"}
    assert "JSON valido: 20/20 (100%)" in capsys.readouterr().out


def test_caso_invalido_mesmo_com_retry_reprova(tmp_path):
    codigo, relatorio = _rodar(tmp_path, _modelo("nao e json", "ainda nao"), "--casos", "caso-01")

    assert codigo == 1
    assert relatorio["resultados"][0]["valido"] is False and relatorio["resultados"][0]["tentativas"] == 2


def test_retry_conta_como_valido(tmp_path):
    codigo, relatorio = _rodar(tmp_path, _modelo("nao e json"), "--casos", "caso-01")

    assert codigo == 0 and relatorio["resultados"][0]["tentativas"] == 2


def test_nomes_plantados_nao_chegam_ao_modelo(tmp_path):
    modelo = _modelo()
    _rodar(tmp_path, modelo, "--casos", "caso-01")

    caso = json.loads((avaliar_soap.CASOS_DIR / "caso-01.json").read_text(encoding="utf-8"))
    for nome in caso["pii_plantada"]["nome_completo"]:
        assert nome not in modelo.chamadas[0]
    for cpf in caso["pii_plantada"]["cpf"]:
        assert cpf not in modelo.chamadas[0]


def test_cota_esgotada_espera_e_tenta_de_novo(tmp_path):
    erro = LlmError("429 RESOURCE_EXHAUSTED", cota_esgotada=True)
    codigo, relatorio = _rodar(tmp_path, _modelo(erro), "--casos", "caso-01")

    assert codigo == 0 and relatorio["resultados"][0]["valido"] is True


def test_retomar_pula_os_casos_ja_avaliados(tmp_path):
    _rodar(tmp_path, _modelo(), "--casos", "caso-01", "caso-02")
    modelo = _modelo()

    codigo = avaliar_soap.main(["--intervalo", "0", "--retomar", str(tmp_path / "rel.json")], chamar_modelo=modelo)

    relatorio = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    assert codigo == 0 and len(relatorio["resultados"]) == 20
    assert len(modelo.chamadas) == 18  # so os que faltavam


def test_falha_que_nao_e_cota_salva_progresso_e_para(tmp_path):
    codigo, relatorio = _rodar(tmp_path, _modelo(SOAP, RuntimeError("rede")), "--casos", "caso-01", "caso-02")

    assert codigo == 2
    assert [r["id"] for r in relatorio["resultados"]] == ["caso-01"]


def test_cid10_subcategoria_do_esperado_conta_como_acerto():
    assert avaliar_soap.cid10_acertou(["R50"], ["R50.9", "B34.9"]) is True
    assert avaliar_soap.cid10_acertou(["G44.2"], ["G44.2"]) is True
    assert avaliar_soap.cid10_acertou(["G44.2"], ["G44"]) is False  # menos especifico
    assert avaliar_soap.cid10_acertou(["R50"], ["R509"]) is False
    assert avaliar_soap.cid10_acertou(["I10"], ["I11.9"]) is False
