"""Diferenca entre a versao do SOAP da IA e a do medico (B44 / US018).

As duas versoes ja chegam validadas pelo SoapV1 (schema.py, B39). Aqui so o
diff por secao que a extensao exibe (SoapDiff):

- secoes de texto (subjetivo, objetivo, avaliacao, plano): diff por palavra;
- listas (hipoteses, alertas, pendencias): diff por item. A hipotese e
  comparada pelo texto "descricao (CID) · confianca X", entao trocar so o
  CID ou a confianca tambem aparece como item alterado.
"""
import difflib
import re

from .schema import SECOES

TITULOS = {
    "subjetivo": "Subjetivo",
    "objetivo": "Objetivo",
    "avaliacao": "Avaliação",
    "plano": "Plano",
    "hipoteses": "Hipóteses",
    "alertas": "Alertas",
    "pendencias": "Pendências",
}
LISTAS = ("hipoteses", "alertas", "pendencias")

# Palavras e espacos como tokens separados: o texto e remontado sem perda.
_TOKENS = re.compile(r"\s+|\S+")


def _texto_do_item(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    texto = item.get("descricao") or ""
    if item.get("cid10"):
        texto += f" ({item['cid10']})"
    if item.get("confianca"):
        texto += f" · confiança {item['confianca']}"
    return texto


def _trechos(antes: list[str], depois: list[str], por_item: bool) -> list[dict]:
    """Opcodes do difflib -> [{"op": igual|removido|adicionado, "texto"}].

    No texto, tokens vizinhos com a mesma operacao viram um trecho so; nas
    listas, cada item e um trecho.
    """
    trechos = []

    def _add(op, tokens):
        if not tokens:
            return
        if por_item:
            trechos.extend({"op": op, "texto": t} for t in tokens)
        elif trechos and trechos[-1]["op"] == op:
            trechos[-1]["texto"] += "".join(tokens)
        else:
            trechos.append({"op": op, "texto": "".join(tokens)})

    matcher = difflib.SequenceMatcher(a=antes, b=depois, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _add("igual", antes[i1:i2])
        else:
            # "replace" mostra o que saiu antes do que entrou, como um revisor
            _add("removido", antes[i1:i2])
            _add("adicionado", depois[j1:j2])
    return trechos


def calcular_diff(versao_ia: dict, versao_medico: dict | None) -> dict | None:
    """Diff por secao do SoapV1; None enquanto o medico nao editou."""
    if versao_medico is None:
        return None
    secoes = []
    for chave in (*SECOES, *LISTAS):
        if chave in LISTAS:
            antes = [_texto_do_item(i) for i in versao_ia.get(chave) or []]
            depois = [_texto_do_item(i) for i in versao_medico.get(chave) or []]
            trechos, tipo = _trechos(antes, depois, por_item=True), "lista"
        else:
            antes = _TOKENS.findall(versao_ia.get(chave) or "")
            depois = _TOKENS.findall(versao_medico.get(chave) or "")
            trechos, tipo = _trechos(antes, depois, por_item=False), "texto"
        secoes.append({
            "secao": chave,
            "titulo": TITULOS[chave],
            "tipo": tipo,
            "alterada": any(t["op"] != "igual" for t in trechos),
            "trechos": trechos,
        })
    alteradas = [s["secao"] for s in secoes if s["alterada"]]
    return {"alterado": bool(alteradas), "secoes_alteradas": alteradas, "secoes": secoes}
