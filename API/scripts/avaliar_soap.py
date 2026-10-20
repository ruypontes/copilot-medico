"""Avaliacao do gerador de SOAP nos 20 casos sinteticos (B40 / B45).

Criterio de aceite do B40: JSON valido (SoapV1 + regras de conteudo) em 100%
dos 20 casos. Para cada caso de eval/cases:

1. anonimiza a transcricao (como a rota faz) e confere que nenhuma PII
   plantada no caso chega ao modelo;
2. gera o SOAP com o prompt versionado e 1 retry (backend/soap/gerador.py);
3. registra se ficou valido, quantas tentativas, a latencia e se o CID-10
   esperado apareceu nas hipoteses (informativo; a completude e do B46).

Uso (na pasta API, com GEMINI_API_KEY valida):

    python scripts/avaliar_soap.py                     # os 20 casos
    python scripts/avaliar_soap.py --casos caso-01 caso-02
    python scripts/avaliar_soap.py --retomar eval/reports/soap_v1_....json

A cota gratuita do Gemini e baixa: o script espaca as chamadas (--intervalo),
espera e tenta de novo quando ela estoura (--espera) e grava o resultado de
cada caso no relatorio, para retomar de onde parou. Sai com codigo 0 so se
todos os casos avaliados gerarem SOAP valido (o criterio do B40).

PII que escapa da anonimizacao e medida e destacada no relatorio, mas nao
muda o codigo de saida: e falha do anonimizador (B25/B26), coberta pelo B47.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from backend.anonimizacao import anonimizar  # noqa: E402
from backend.soap import gerador  # noqa: E402

CASOS_DIR = API_DIR / "eval" / "cases"
REPORTS_DIR = API_DIR / "eval" / "reports"


def _pii(caso: dict) -> list[str]:
    return [valor for valores in caso.get("pii_plantada", {}).values() for valor in valores]


def material_do_caso(caso: dict) -> str:
    """O caso so tem a transcricao; vira a mesma secao que a rota monta."""
    return f"## Transcrição da consulta\n{caso['transcricao']}"


def cid10_acertou(esperados: list[str], gerados: list[str]) -> bool:
    """Acerto se algum CID gerado e o esperado ou uma subcategoria dele
    (esperado R50, gerado R50.9). O contrario tambem vale: esperado G44.2,
    gerado so a categoria G44 nao conta - falta especificidade."""
    return any(g == e or g.startswith(e + ".") for e in esperados for g in gerados)


def avaliar_caso(caso: dict, chamar_modelo) -> dict:
    nomes = caso.get("pii_plantada", {}).get("nome_completo", [])
    texto = anonimizar(material_do_caso(caso), nomes_conhecidos=nomes).texto
    vazou = [valor for valor in _pii(caso) if valor in texto]

    inicio = time.perf_counter()
    resultado = {"id": caso["id"], "pii_vazada": vazou}
    try:
        gerado = gerador.gerar_soap(texto, chamar_modelo)
        hipoteses = [h.cid10 for h in gerado.soap.hipoteses if h.cid10]
        resultado.update(
            valido=True,
            tentativas=gerado.tentativas,
            erros=[],
            cid10_esperado=caso.get("cid10_esperado", []),
            cid10_gerado=hipoteses,
            cid10_acertou=cid10_acertou(caso.get("cid10_esperado", []), hipoteses),
        )
    except gerador.SoapNaoGerado as erro:
        resultado.update(valido=False, tentativas=erro.tentativas, erros=erro.erros)
    resultado["latencia_s"] = round(time.perf_counter() - inicio, 2)
    return resultado


def _cota_esgotada(erro: Exception) -> bool:
    return type(erro).__name__ in {"ResourceExhausted", "TooManyRequests"}


def resumo(resultados: list[dict]) -> str:
    validos = sum(r.get("valido", False) for r in resultados)
    total = len(resultados)
    linhas = [
        f"Prompt: {gerador.PROMPT_ID} v{gerador.PROMPT_VERSAO}",
        f"Casos avaliados: {total}",
        f"JSON valido: {validos}/{total} ({100 * validos / total:.0f}%)" if total else "JSON valido: -",
        f"Precisaram de retry: {sum(r.get('tentativas') == 2 and r.get('valido') for r in resultados)}",
        f"CID-10 esperado entre as hipoteses: {sum(r.get('cid10_acertou', False) for r in resultados)}/{total}",
        f"PII vazada para o modelo: {sum(bool(r['pii_vazada']) for r in resultados)} caso(s)",
        "",
        f"{'caso':10}{'valido':8}{'tent.':7}{'lat.(s)':9}{'CID ok':8}",
    ]
    for r in resultados:
        linhas.append(
            f"{r['id']:10}{('sim' if r.get('valido') else 'NAO'):8}{r.get('tentativas', '-')!s:7}"
            f"{r.get('latencia_s', '-')!s:9}{('sim' if r.get('cid10_acertou') else '-'):8}"
        )
        for erro in r.get("erros", []):
            linhas.append(f"    erro: {erro}")
        if r["pii_vazada"]:
            linhas.append(f"    PII vazada: {r['pii_vazada']}")
    return "\n".join(linhas)


def main(argv=None, chamar_modelo=None) -> int:
    parser = argparse.ArgumentParser(description="Avalia o gerador de SOAP nos casos do B45 (B40).")
    parser.add_argument("--casos", nargs="*", help="ids a avaliar (padrao: todos)")
    parser.add_argument("--intervalo", type=float, default=6.0, help="segundos entre casos (cota)")
    parser.add_argument("--espera", type=float, default=60.0, help="segundos de espera se a cota estourar")
    parser.add_argument("--max-esperas", type=int, default=5)
    parser.add_argument("--retomar", type=Path, help="relatorio anterior: pula os casos ja avaliados")
    parser.add_argument("--saida", type=Path, help="arquivo do relatorio (padrao: eval/reports/...)")
    args = parser.parse_args(argv)

    if chamar_modelo is None:
        from backend.llm import chat

        chamar_modelo = chat.gerar_resposta_unica

    casos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASOS_DIR.glob("caso-*.json"))]
    if args.casos:
        casos = [c for c in casos if c["id"] in set(args.casos)]

    saida = args.retomar or args.saida or REPORTS_DIR / (
        f"soap_v{gerador.PROMPT_VERSAO}_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    resultados = json.loads(saida.read_text(encoding="utf-8"))["resultados"] if args.retomar else []
    feitos = {r["id"] for r in resultados}
    saida.parent.mkdir(parents=True, exist_ok=True)

    def gravar():
        saida.write_text(json.dumps({
            "prompt": {"id": gerador.PROMPT_ID, "versao": gerador.PROMPT_VERSAO},
            "resultados": resultados,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    pendentes = [c for c in casos if c["id"] not in feitos]
    for indice, caso in enumerate(pendentes):
        for espera in range(args.max_esperas + 1):
            try:
                resultado = avaliar_caso(caso, chamar_modelo)
                break
            except Exception as erro:
                if not _cota_esgotada(erro) or espera == args.max_esperas:
                    gravar()
                    print(f"\n{caso['id']}: falha na chamada ({type(erro).__name__}). "
                          f"Progresso salvo; retome com --retomar {saida}")
                    return 2
                print(f"{caso['id']}: cota do Gemini esgotada; aguardando {args.espera:.0f}s...")
                time.sleep(args.espera)
        resultados.append(resultado)
        gravar()
        print(f"{caso['id']}: {'valido' if resultado['valido'] else 'INVALIDO'} "
              f"({resultado['tentativas']} tentativa(s), {resultado['latencia_s']}s)")
        if indice < len(pendentes) - 1:
            time.sleep(args.intervalo)

    print("\n" + resumo(resultados))
    if any(r["pii_vazada"] for r in resultados):
        print("\nATENCAO: houve PII plantada que chegou ao modelo (ver 'PII vazada' acima). "
              "E falha do anonimizador (B25/B26), coberta pelo B47 - nao do gerador de SOAP.")
    print(f"\nRelatorio: {saida}")
    return 0 if resultados and all(r["valido"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
