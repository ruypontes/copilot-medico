"""run_eval.py v1 (B46 / US022): metricas, retry, provedores, relatorio e CLI.

Nada aqui chama rede: o provedor real (Gemini) e exercitado com um modelo falso,
e o harness com provedores falsos que devolvem respostas fabricadas para cada
situacao (valida, invalida, curta, falha). Os valores esperados das metricas
sao calculados a mao nos proprios testes.
"""
from __future__ import annotations

import json
import sys
import types
import wave
from datetime import date
from pathlib import Path

import pytest

from eval import run_eval as ev
from eval.soap_provisorio import SoapV1

API_DIR = Path(__file__).resolve().parents[1]
CASOS = API_DIR / "tests" / "fixtures" / "cases"
SEGREDO_NO_CASO = "SEGREDO-NO-CASO"
SEGREDO_NA_SAIDA = "SEGREDO-NA-SAIDA"


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

def soap_json(palavras=25, **sobrescrever) -> str:
    """SOAP valido com `palavras` palavras em cada secao."""
    texto = " ".join(["palavra"] * palavras)
    dados = {
        "subjetivo": texto, "objetivo": texto, "avaliacao": texto, "plano": texto,
        "hipoteses": [{"descricao": "Hipotese", "cid10": "A90", "confianca": "media"}],
        "alertas": [], "pendencias": [],
    }
    dados.update(sobrescrever)
    return json.dumps(dados, ensure_ascii=False)


def resposta(texto, tokens_entrada=100, tokens_saida=50, estimado=False):
    return ev.Resposta(texto, tokens_entrada, tokens_saida, estimado)


class ProvedorFalso:
    nome = "falso"
    modelo = "falso"
    modelo_preco = "gemini-2.5-flash"

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.erros_recebidos: list = []

    def gerar(self, caso, erro_anterior=None):
        self.erros_recebidos.append(erro_anterior)
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def precos():
    return ev.carregar_precos(ev.PRECOS_PADRAO)


@pytest.fixture()
def caso():
    return {"id": "caso-x", "transcricao": [{"papel": "medico", "texto": f"Ola {SEGREDO_NO_CASO}"}]}


def avaliar(caso, provedor, precos):
    return ev.avaliar_caso(caso, provedor, SoapV1, precos)


# ---------------------------------------------------------------------------
# Contagem de palavras e percentis
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("", 0),
    ("   ", 0),
    ("uma duas tres", 3),
    ("dor-de-cabeca forte", 2),          # hifen nao separa palavra
    ("- ... , 12 mg", 2),                # pontuacao solta nao conta; numero conta
    (None, 0),
    (123, 0),
])
def test_contar_palavras(texto, esperado):
    assert ev.contar_palavras(texto) == esperado


def test_percentil_posto_mais_proximo():
    valores = list(range(1, 11))  # 1..10
    assert ev.percentil(valores, 50) == 5
    assert ev.percentil(valores, 95) == 10
    assert ev.percentil([7.0], 95) == 7.0
    assert ev.percentil([3, 1, 2], 50) == 2  # nao exige entrada ordenada
    assert ev.percentil([], 50) is None


# ---------------------------------------------------------------------------
# JSON valido
# ---------------------------------------------------------------------------

def test_soap_valido_passa():
    objeto, motivo = ev.validar_soap(soap_json(), SoapV1)
    assert motivo is None and objeto.hipoteses[0].cid10 == "A90"


@pytest.mark.parametrize("texto", [
    "isto nao e json",
    "```json\n" + soap_json() + "\n```",            # cerca de codigo: estrito, invalido
    "[1, 2, 3]",                                      # JSON, mas nao objeto
    json.dumps({"subjetivo": "so isto"}),            # faltam campos
    soap_json(extra="chave inventada"),               # extra=forbid
    soap_json(subjetivo=""),                          # secao vazia
    soap_json(hipoteses=[{"descricao": "x", "cid10": "A90", "confianca": "70%"}]),  # confianca fora do enum
    None,
])
def test_soap_invalido_e_rejeitado(texto):
    objeto, motivo = ev.validar_soap(texto, SoapV1)
    assert objeto is None and motivo


def test_motivo_do_erro_nao_traz_o_valor_recebido():
    texto = soap_json(hipoteses=[{"descricao": "x", "cid10": "A90", "confianca": SEGREDO_NA_SAIDA}])
    _, motivo = ev.validar_soap(texto, SoapV1)
    assert SEGREDO_NA_SAIDA not in motivo
    assert "hipoteses.0.confianca" in motivo


# ---------------------------------------------------------------------------
# Custo equivalente
# ---------------------------------------------------------------------------

def test_custo_soma_tokens_e_audio():
    precos = {"usd_brl": 5.0, "modelos": {"m": {
        "entrada_usd_por_milhao_tokens": 0.30, "saida_usd_por_milhao_tokens": 2.50, "audio_usd_por_minuto": 0.002,
    }}}
    # 1M entrada (0,30) + 1M saida (2,50) + 10 min de audio (0,02) = US$ 2,82 -> R$ 14,10
    assert ev.calcular_custo_brl(precos, "m", 1_000_000, 1_000_000, 10) == pytest.approx(14.10)
    assert ev.calcular_custo_brl(precos, "m", 0, 0, 0) == 0
    assert ev.calcular_custo_brl(precos, "modelo-fora-da-tabela", 1000, 1000, 1) is None


def test_tabela_de_precos_padrao_e_valida_e_cobre_o_modelo_padrao():
    precos = ev.carregar_precos(ev.PRECOS_PADRAO)
    assert ev.MODELO_GEMINI_PADRAO in precos["modelos"]
    assert precos["verificado"] is False, "ao conferir os precos, troque para true e preencha fonte e data"


def test_tabela_de_precos_invalida(tmp_path):
    ruim = tmp_path / "p.json"
    ruim.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ev.carregar_precos(ruim)
    ruim.write_text("nao e json", encoding="utf-8")
    with pytest.raises(ValueError):
        ev.carregar_precos(ruim)


# ---------------------------------------------------------------------------
# Um caso: tentativa, retry, completude, falhas
# ---------------------------------------------------------------------------

def test_caso_valido_na_primeira(caso, precos):
    provedor = ProvedorFalso(resposta(soap_json(25), 1000, 500))

    r = avaliar(caso, provedor, precos)

    assert r.avaliado and r.valido_1a and r.valido_final and r.completo
    assert len(r.tentativas) == 1
    assert r.palavras == {"subjetivo": 25, "objetivo": 25, "avaliacao": 25, "plano": 25}
    assert (r.tokens_entrada, r.tokens_saida) == (1000, 500)
    # 1000 ent (0,30/M) + 500 saida (2,50/M) = US$ 0,00155 -> R$ 0,008525
    assert r.custo_brl == pytest.approx(0.00155 * 5.5)


def test_invalido_depois_valido_conta_o_retry_e_soma_latencia_tokens_e_custo(caso, precos):
    provedor = ProvedorFalso(resposta("nao e json", 1000, 100), resposta(soap_json(25), 1100, 400))

    r = avaliar(caso, provedor, precos)

    assert r.valido_1a is False and r.valido_final is True and r.completo is True
    assert len(r.tentativas) == 2
    assert [t.valida for t in r.tentativas] == [False, True]
    assert (r.tokens_entrada, r.tokens_saida) == (2100, 500)
    assert r.custo_brl == pytest.approx((2100 / 1e6 * 0.30 + 500 / 1e6 * 2.50) * 5.5)
    # a 2a tentativa recebe o MOTIVO da falha (sem conteudo) para corrigir
    assert provedor.erros_recebidos[0] is None
    assert "JSON malformado" in provedor.erros_recebidos[1]


def test_invalido_nas_duas_tentativas_nao_tem_terceira(caso, precos):
    provedor = ProvedorFalso(resposta("lixo"), resposta("lixo de novo"), resposta(soap_json()))

    r = avaliar(caso, provedor, precos)

    assert r.avaliado and not r.valido_1a and not r.valido_final and not r.completo
    assert len(r.tentativas) == 2 and r.palavras is None
    assert len(provedor.respostas) == 1  # a terceira resposta nunca foi pedida


@pytest.mark.parametrize("palavras, completo", [(20, True), (19, False)])
def test_limite_de_20_palavras_por_secao(caso, precos, palavras, completo):
    r = avaliar(caso, ProvedorFalso(resposta(soap_json(25, plano=" ".join(["w"] * palavras)))), precos)
    assert r.completo is completo
    assert r.palavras["plano"] == palavras


def test_erro_do_provedor_e_registrado_sem_a_mensagem(caso, precos):
    provedor = ProvedorFalso(RuntimeError(f"429 quota exceeded {SEGREDO_NO_CASO}"))

    r = avaliar(caso, provedor, precos)

    assert not r.avaliado and r.tentativas == []
    assert "cota" in r.erro_provedor and "RuntimeError" in r.erro_provedor
    assert SEGREDO_NO_CASO not in r.erro_provedor, "a mensagem do erro pode trazer pedacos do pedido"


def test_erro_do_provedor_no_retry_tambem_invalida_a_avaliacao(caso, precos):
    r = avaliar(caso, ProvedorFalso(resposta("lixo"), TimeoutError("timed out")), precos)
    assert not r.avaliado and "tempo esgotado" in r.erro_provedor and len(r.tentativas) == 1


@pytest.mark.parametrize("erro, trecho", [
    (RuntimeError("Error 429: rate limit"), "cota"),
    (RuntimeError("API key not valid"), "chave"),
    (TimeoutError("Deadline exceeded"), "tempo esgotado"),
    (ValueError("response blocked"), "bloqueada"),
    (KeyError("x"), "erro do provedor"),
])
def test_classificacao_de_erros_do_provedor(erro, trecho):
    assert trecho in ev.classificar_erro_provedor(erro)


# ---------------------------------------------------------------------------
# Agregados e metas
# ---------------------------------------------------------------------------

def _resultado(id, valida_1a=True, valida_final=True, palavras=25, latencia=1.0, custo=0.01):
    tentativas = []
    if not valida_1a:
        tentativas.append(ev.Tentativa(False, "x", latencia / 2, 10, 10))
    tentativas.append(ev.Tentativa(valida_final, None if valida_final else "x", latencia / 2 if not valida_1a else latencia, 10, 10))
    r = ev.ResultadoCaso(id=id, tentativas=tentativas, custo_brl=custo)
    if valida_final:
        r.palavras = {s: palavras for s in ev.SECOES}
    return r


def test_agregados_com_valores_conhecidos():
    resultados = [
        _resultado("a"),                                   # valido 1a, completo, 1,0 s
        _resultado("b", valida_1a=False, latencia=3.0),    # valido so com retry, 3,0 s
        _resultado("c", palavras=10, latencia=2.0),        # valido, incompleto, 2,0 s
        _resultado("d", valida_1a=False, valida_final=False, latencia=4.0),  # invalido
    ]
    ag = ev.agregar(resultados)

    assert ag["casos_total"] == ag["casos_avaliados"] == 4
    assert ag["json_valido_1a_pct"] == pytest.approx(50.0)     # a, c
    assert ag["json_valido_final_pct"] == pytest.approx(75.0)  # a, b, c
    assert ag["completude_pct"] == pytest.approx(50.0)         # a, b
    assert ag["latencia_p50_s"] == pytest.approx(2.0)
    assert ag["latencia_p95_s"] == pytest.approx(4.0)
    assert ag["custo_total_brl"] == pytest.approx(0.04)
    assert ag["custo_medio_por_caso_brl"] == pytest.approx(0.01)
    assert ev.avaliar_metas(ag) == {
        "json_valido_final": "abaixo da meta", "completude": "abaixo da meta", "latencia_p95": "ok",
    }


def test_casos_com_erro_do_provedor_ficam_fora_dos_agregados():
    com_erro = ev.ResultadoCaso(id="e", erro_provedor="cota")
    ag = ev.agregar([_resultado("a"), com_erro])

    assert (ag["casos_total"], ag["casos_avaliados"], ag["casos_com_erro_de_provedor"]) == (2, 1, 1)
    assert ag["json_valido_final_pct"] == 100.0


def test_sem_nenhum_caso_avaliado_nao_divide_por_zero():
    ag = ev.agregar([ev.ResultadoCaso(id="e", erro_provedor="cota")])
    assert ag["json_valido_final_pct"] is None and ag["latencia_p95_s"] is None
    assert set(ev.avaliar_metas(ag).values()) == {"sem dados"}


def test_metas_atingidas():
    ag = ev.agregar([_resultado("a"), _resultado("b", latencia=20.0)])
    assert set(ev.avaliar_metas(ag).values()) == {"ok"}   # p95 == 20 s ainda cumpre (<= 20)


def test_p95_acima_de_20s_nao_cumpre_a_meta():
    ag = ev.agregar([_resultado("a", latencia=20.01)])
    assert ev.avaliar_metas(ag)["latencia_p95"] == "abaixo da meta"


# ---------------------------------------------------------------------------
# Casos de referencia
# ---------------------------------------------------------------------------

def test_fixtures_seguem_o_formato_do_docs_09():
    casos = ev.carregar_casos(CASOS)
    assert [c["id"] for c in casos] == ["caso-ex-01-dengue", "caso-ex-02-hipertensao", "caso-ex-03-cefaleia"]
    for c in casos:
        assert c["sintetico"] is True
        dialogo = " ".join(t["texto"] for t in c["transcricao"])
        # docs/09: "cada valor de pii_plantada e inserido no texto" (alimenta o teste de vazamento, B47)
        for valor in c["pii_plantada"]:
            assert valor in dialogo, f"{c['id']}: PII plantada {valor!r} nao esta na transcricao"
        soap = c["gabarito"]["soap"]
        assert all(ev.contar_palavras(soap[s]) >= ev.MIN_PALAVRAS for s in ev.SECOES)


def test_anexo_do_caso_e_carregado_e_entra_no_conteudo():
    dengue = ev.carregar_casos(CASOS)[0]
    assert "hemograma-plaquetas-baixas.txt" in dengue["_documentos"]
    conteudo = ev.montar_conteudo_caso(dengue)
    assert "## Prontuario" in conteudo and "- tempe: 38.9" in conteudo
    assert "Medico: Bom dia" in conteudo and "Paciente: Doutor" in conteudo
    assert "## Documentos anexados" in conteudo and "Plaquetas: 82.000" in conteudo


def test_limite_de_casos():
    assert len(ev.carregar_casos(CASOS, limite=2)) == 2


@pytest.mark.parametrize("conteudo, trecho", [
    ('{"transcricao": [{"papel": "medico", "texto": "x"}]}', "'id'"),
    ('{"id": "a", "transcricao": []}', "transcricao"),
    ('{"id": "a", "transcricao": [{"papel": "medico"}]}', "papel"),
    ('{"id": "a", "transcricao": [{"papel": "medico", "texto": "x"}], "gabarito": []}', "gabarito"),
    ('{"id": "a", "transcricao": [{"papel": "medico", "texto": "x"}], "duracao_min": -1}', "duracao_min"),
    ("[1]", "objeto"),
    ("{nao json", "malformado"),
])
def test_caso_invalido_diz_qual_arquivo_e_o_que_falta(tmp_path, conteudo, trecho):
    (tmp_path / "ruim.json").write_text(conteudo, encoding="utf-8")
    with pytest.raises(ev.CasoInvalido) as erro:
        ev.carregar_casos(tmp_path)
    assert "ruim.json" in str(erro.value) and trecho in str(erro.value)


def test_id_duplicado(tmp_path):
    corpo = '{"id": "a", "transcricao": [{"papel": "medico", "texto": "x"}]}'
    (tmp_path / "1.json").write_text(corpo, encoding="utf-8")
    (tmp_path / "2.json").write_text(corpo, encoding="utf-8")
    with pytest.raises(ev.CasoInvalido, match="duplicado"):
        ev.carregar_casos(tmp_path)


def test_pasta_inexistente_ou_vazia(tmp_path):
    with pytest.raises(ev.CasoInvalido, match="nao encontrada"):
        ev.carregar_casos(tmp_path / "nao-existe")
    with pytest.raises(ev.CasoInvalido, match="nenhum"):
        ev.carregar_casos(tmp_path)


def test_minutos_de_audio(tmp_path, monkeypatch):
    assert ev.minutos_de_audio({"duracao_min": 20}) == 20.0
    assert ev.minutos_de_audio({"id": "sem audio"}) == 0.0
    (tmp_path / "audio").mkdir()
    with wave.open(str(tmp_path / "audio" / "a.wav"), "wb") as wav:
        wav.setnchannels(1), wav.setsampwidth(2), wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000 * 90)   # 90 s
    monkeypatch.setattr(ev, "EVAL_DIR", tmp_path)
    assert ev.minutos_de_audio({"audio": "a.wav"}) == pytest.approx(1.5)
    assert ev.minutos_de_audio({"audio": "nao-existe.wav"}) == 0.0
    (tmp_path / "audio" / "ponteiro.wav").write_text("version https://git-lfs...", encoding="utf-8")
    assert ev.minutos_de_audio({"audio": "ponteiro.wav"}) == 0.0   # arquivo LFS nao baixado


# ---------------------------------------------------------------------------
# Provedores
# ---------------------------------------------------------------------------

def test_mock_gera_soap_valido_e_completo_para_cada_fixture(precos):
    for c in ev.carregar_casos(CASOS):
        r = avaliar(c, ev.ProvedorMock(), precos)
        assert r.valido_1a and r.completo, c["id"]
        assert r.tokens_estimados


def test_mock_e_deterministico_e_aproveita_o_cid_do_gabarito():
    c = ev.carregar_casos(CASOS)[0]
    primeira, segunda = ev.ProvedorMock().gerar(c), ev.ProvedorMock().gerar(c)
    assert primeira.texto == segunda.texto
    assert json.loads(primeira.texto)["hipoteses"][0]["cid10"] == "A90"


def test_mock_sem_gabarito_ainda_devolve_json_valido(precos):
    c = {"id": "sem-gabarito", "transcricao": [{"papel": "medico", "texto": "so uma frase"}]}
    assert avaliar(c, ev.ProvedorMock(), precos).valido_1a


class ModeloGeminiFalso:
    def __init__(self, texto, uso=None, erro=None):
        self.texto, self.uso, self.erro, self.pedidos = texto, uso, erro, []

    def generate_content(self, conteudo):
        self.pedidos.append(conteudo)
        if self.erro:
            raise self.erro
        return types.SimpleNamespace(text=self.texto, usage_metadata=self.uso)


def test_gemini_usa_os_tokens_informados_e_soma_o_pensamento_na_saida():
    uso = types.SimpleNamespace(prompt_token_count=1200, candidates_token_count=300, thoughts_token_count=700)
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "prompt", ModeloGeminiFalso(soap_json(), uso))

    r = provedor.gerar(ev.carregar_casos(CASOS)[0])

    assert (r.tokens_entrada, r.tokens_saida, r.estimado) == (1200, 1000, False)


def test_gemini_deriva_o_pensamento_do_total_quando_o_sdk_nao_expoe_o_campo():
    """Sem thoughts_token_count na resposta, o total inclui o pensamento (cobrado como saida)."""
    uso = types.SimpleNamespace(prompt_token_count=1000, candidates_token_count=300, total_token_count=2000)
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "p", ModeloGeminiFalso(soap_json(), uso))

    r = provedor.gerar(ev.carregar_casos(CASOS)[0])

    assert (r.tokens_entrada, r.tokens_saida) == (1000, 1000)   # 300 + (2000 - 1000 - 300)


def test_gemini_sem_pensamento_nem_total_nao_inventa_tokens():
    uso = types.SimpleNamespace(prompt_token_count=1000, candidates_token_count=300)
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "p", ModeloGeminiFalso(soap_json(), uso))
    assert provedor.gerar(ev.carregar_casos(CASOS)[0]).tokens_saida == 300


def test_gemini_estima_tokens_se_o_uso_nao_vier():
    provedor = ev.ProvedorGemini("chave", "m", "p", ModeloGeminiFalso(soap_json(), uso=None))
    r = provedor.gerar(ev.carregar_casos(CASOS)[0])
    assert r.estimado and r.tokens_entrada > 0 and r.tokens_saida > 0


def test_gemini_reenvia_o_motivo_da_falha_no_retry():
    modelo = ModeloGeminiFalso(soap_json())
    provedor = ev.ProvedorGemini("chave", "m", "p", modelo)
    c = ev.carregar_casos(CASOS)[0]

    provedor.gerar(c)
    provedor.gerar(c, erro_anterior="hipoteses.0.confianca: literal_error")

    assert "rejeitada" not in modelo.pedidos[0]
    assert "rejeitada na validacao (hipoteses.0.confianca: literal_error)" in modelo.pedidos[1]


def test_gemini_resposta_bloqueada_vira_erro_do_provedor(precos):
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "p", ModeloGeminiFalso("", erro=ValueError("blocked")))
    r = avaliar(ev.carregar_casos(CASOS)[0], provedor, precos)
    assert not r.avaliado and "bloqueada" in r.erro_provedor


def _genai_falso(texto):
    """SDK google-genai falso: guarda cada generate_content recebido (B41)."""
    sdk = types.SimpleNamespace(clientes=[], chamadas=[])

    def generate_content(**kwargs):
        sdk.chamadas.append(kwargs)
        return types.SimpleNamespace(text=texto, usage_metadata=None)

    def cliente(**kwargs):
        sdk.clientes.append(kwargs)
        return types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))

    sdk.Client = cliente
    return sdk


def test_modelo_genai_pede_json_com_o_prompt_como_instrucao():
    sdk = _genai_falso(soap_json())
    modelo = ev._ModeloGenai("chave", "gemini-2.5-flash", "prompt do eval", genai_mod=sdk)
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "p", modelo)

    assert provedor.gerar(ev.carregar_casos(CASOS)[0]).texto == soap_json()
    assert sdk.clientes == [{"api_key": "chave"}]
    chamada = sdk.chamadas[0]
    assert chamada["model"] == "gemini-2.5-flash"
    assert chamada["config"] == {
        "system_instruction": "prompt do eval",
        "response_mime_type": "application/json",
        "temperature": 0.2,
    }


def test_modelo_genai_resposta_sem_texto_vira_erro_do_provedor(precos):
    # google-genai devolve text=None em vez de levantar quando bloqueia
    modelo = ev._ModeloGenai("chave", "gemini-2.5-flash", "p", genai_mod=_genai_falso(None))
    provedor = ev.ProvedorGemini("chave", "gemini-2.5-flash", "p", modelo)
    r = avaliar(ev.carregar_casos(CASOS)[0], provedor, precos)
    assert not r.avaliado and "bloqueada" in r.erro_provedor


def test_gemini_exige_chave(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    args = ev.ler_argumentos(["--provedor", "gemini"])
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        ev.construir_provedor(args, "prompt")


def test_pausa_entre_casos_e_so_entre_eles(monkeypatch, precos):
    esperas = []
    monkeypatch.setattr(ev.time, "sleep", esperas.append)
    ev.executar(ev.carregar_casos(CASOS), ev.ProvedorMock(), SoapV1, precos, pausa_s=7.0, log=lambda m: None)
    assert esperas == [7.0, 7.0]      # 3 casos => 2 pausas
    esperas.clear()
    ev.executar(ev.carregar_casos(CASOS), ev.ProvedorMock(), SoapV1, precos, pausa_s=0.0, log=lambda m: None)
    assert esperas == []


# ---------------------------------------------------------------------------
# Schema: oficial (B39) tem prioridade sobre o provisorio
# ---------------------------------------------------------------------------

def test_usa_o_schema_provisorio_enquanto_o_oficial_nao_existe(monkeypatch):
    monkeypatch.delitem(sys.modules, "soap", raising=False)
    monkeypatch.delitem(sys.modules, "soap.schema", raising=False)
    schema, origem = ev.carregar_schema()
    assert schema is SoapV1 and origem.startswith("provisorio")


def test_usa_o_schema_oficial_quando_a_b39_chegar(monkeypatch):
    oficial = type("SoapV1", (), {})
    pacote, modulo = types.ModuleType("soap"), types.ModuleType("soap.schema")
    modulo.SoapV1 = oficial
    pacote.schema = modulo
    monkeypatch.setitem(sys.modules, "soap", pacote)
    monkeypatch.setitem(sys.modules, "soap.schema", modulo)

    schema, origem = ev.carregar_schema()

    assert schema is oficial and origem.startswith("oficial")


def test_prompt_provisorio_esta_alinhado_ao_schema_e_a_us018_ca002():
    prompt = ev.PROMPT_PADRAO.read_text(encoding="utf-8")
    for campo in SoapV1.model_fields:
        assert f'"{campo}"' in prompt, f"o prompt nao descreve o campo {campo}"
    assert "referencias bibliograficas" in prompt and "Nao inclua" in prompt
    assert "%" not in prompt, "o prompt nao deve pedir percentuais (US018-CA002)"


# ---------------------------------------------------------------------------
# Relatorio
# ---------------------------------------------------------------------------

def _gerar(provedor_nome="falso", resultados=None, precos=None):
    resultados = resultados or [_resultado("caso-a"), _resultado("caso-b", valida_1a=False, latencia=2.0)]
    ag = ev.agregar(resultados)
    meta = {"data": "2026-10-16", "provedor": provedor_nome, "modelo": "m", "prompt_versao": "p1",
            "schema": "provisorio", "casos": "tests/fixtures/cases"}
    precos = precos or ev.carregar_precos(ev.PRECOS_PADRAO)
    return ev.gerar_markdown(meta, resultados, ag, ev.avaliar_metas(ag), precos), meta, resultados, ag


def test_nome_do_relatorio():
    assert ev.nome_relatorio(date(2026, 10, 16), "gemini", "soap-v2") == "2026-10-16-gemini-soap-v2.md"


def test_relatorio_tem_agregado_por_caso_e_precos():
    md, *_ = _gerar()
    assert "# Relatório de avaliação da IA (run_eval v1)" in md
    for trecho in ("## Resultado agregado", "## Por caso", "## Casos com problema", "## Preços usados",
                   "| caso-a |", "| caso-b |", "JSON válido (com 1 retry)", "Latência p95", "Custo equivalente"):
        assert trecho in md, trecho
    assert "tentativa 1 inválida" in md      # caso-b precisou de retry


def test_aviso_de_mock_so_aparece_no_mock():
    assert "provedor MOCK" in _gerar("mock")[0]
    assert "provedor MOCK" not in _gerar("gemini")[0]


def test_aviso_de_precos_so_enquanto_nao_verificados(precos):
    assert "tabela de preços ilustrativa" in _gerar(precos=precos)[0]
    verificados = {**precos, "verificado": True}
    assert "tabela de preços ilustrativa" not in _gerar(precos=verificados)[0]


def test_relatorio_lista_casos_sem_resposta_do_provedor():
    md, *_ = _gerar(resultados=[_resultado("ok"), ev.ResultadoCaso(id="sem-resposta", erro_provedor="limite de cota (429) [X]")])
    assert "1 caso(s) sem resposta do provedor" in md
    assert "**sem-resposta**: sem resposta do provedor: limite de cota (429) [X]" in md


def test_relatorio_e_json_nao_vazam_texto_do_caso_nem_da_saida_do_modelo(caso, precos):
    """Tudo que o provedor devolve e tudo que o caso contem fica FORA dos relatorios."""
    saida_invalida = json.dumps({"subjetivo": SEGREDO_NA_SAIDA, "confianca": SEGREDO_NA_SAIDA})
    provedor = ProvedorFalso(resposta(saida_invalida), resposta(SEGREDO_NA_SAIDA))
    r = avaliar(caso, provedor, precos)
    md, meta, resultados, ag = _gerar(resultados=[r])
    como_json = json.dumps(ev.dados_json(meta, resultados, ag, ev.avaliar_metas(ag)), ensure_ascii=False)

    for segredo in (SEGREDO_NO_CASO, SEGREDO_NA_SAIDA):
        assert segredo not in md and segredo not in como_json


# ---------------------------------------------------------------------------
# CLI ponta a ponta
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def sem_dotenv_real(monkeypatch):
    """O main() carrega API/.env; um .env de desenvolvedor nao pode mudar o resultado dos testes."""
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)


def test_cli_com_mock_gera_o_relatorio_markdown_e_o_json(tmp_path, capsys):
    codigo = ev.main(["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "2026-10-16"])

    assert codigo == 0
    md = tmp_path / "2026-10-16-mock-soap-provisorio-v1.md"
    js = md.with_suffix(".json")
    assert md.is_file() and js.is_file()
    assert "caso-ex-02-hipertensao" in md.read_text(encoding="utf-8")
    dados = json.loads(js.read_text(encoding="utf-8"))
    assert dados["agregado"]["casos_total"] == 3 and dados["metas"]["json_valido_final"] == "ok"
    assert "Relatorio:" in capsys.readouterr().out


def test_cli_limite(tmp_path):
    ev.main(["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "2026-10-16", "--limite", "1"])
    dados = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert dados["agregado"]["casos_total"] == 1


def test_cli_cria_a_pasta_do_relatorio(tmp_path):
    destino = tmp_path / "a" / "b"
    assert ev.main(["--casos", str(CASOS), "--saida", str(destino), "--data", "2026-10-16"]) == 0
    assert any(destino.glob("*.md"))


def test_cli_pasta_de_casos_inexistente_sai_com_2(tmp_path, capsys):
    assert ev.main(["--casos", str(tmp_path / "nada"), "--saida", str(tmp_path)]) == 2
    assert "nao encontrada" in capsys.readouterr().err


def test_cli_dica_a_b45_quando_a_pasta_padrao_nao_existe(tmp_path, capsys):
    if ev.CASOS_PADRAO.exists():
        pytest.skip("eval/cases ja existe (B45 entregue)")
    assert ev.main(["--saida", str(tmp_path)]) == 2
    assert "B45" in capsys.readouterr().err


def test_cli_gemini_sem_chave_sai_com_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert ev.main(["--provedor", "gemini", "--casos", str(CASOS), "--saida", str(tmp_path)]) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == [], "sem chave nao deve sobrar relatorio"


def test_cli_data_invalida_sai_com_2(tmp_path):
    assert ev.main(["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "16/10/2026"]) == 2


def test_cli_estrito_falha_se_uma_meta_nao_for_atingida(tmp_path, monkeypatch, capsys):
    ruim = ProvedorFalso(*[resposta("lixo")] * 6)     # 3 casos x 2 tentativas, tudo invalido
    monkeypatch.setattr(ev, "construir_provedor", lambda args, prompt: ruim)
    argv = ["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "2026-10-16"]

    assert ev.main(argv) == 0                  # sem --estrito: gera o relatorio e segue
    ruim.respostas = [resposta("lixo")] * 6
    assert ev.main([*argv, "--estrito"]) == 1
    assert "json_valido_final" in capsys.readouterr().err


def test_cli_estrito_falha_se_algum_caso_ficou_sem_resposta(tmp_path, monkeypatch):
    falho = ProvedorFalso(resposta(soap_json()), RuntimeError("429"), resposta(soap_json()))
    monkeypatch.setattr(ev, "construir_provedor", lambda args, prompt: falho)
    argv = ["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "2026-10-16", "--estrito"]
    assert ev.main(argv) == 1


def test_cli_estrito_passa_quando_tudo_esta_na_meta(tmp_path):
    assert ev.main(["--casos", str(CASOS), "--saida", str(tmp_path), "--data", "2026-10-16", "--estrito"]) == 0
