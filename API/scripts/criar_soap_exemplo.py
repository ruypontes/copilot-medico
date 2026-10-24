"""Cria um SOAP "gerado pela IA" de exemplo numa consulta (B44, so para dev).

Cria um SOAP sem chamar a IA (o gerador e o B40: POST .../soap). Util para
testar a edicao do medico e o diff sem gastar cota (GET /api/consultations/<id>/soap e PUT .../soap/<soap_id>). O
conteudo e ficticio e segue o SoapV1 (B39).

    python scripts/criar_soap_exemplo.py <consultation_id>
    python scripts/criar_soap_exemplo.py <consultation_id> --arquivo meu_soap.json

No Docker:

    docker compose exec backend python scripts/criar_soap_exemplo.py <consultation_id>
"""
import argparse
import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from backend.soap import SoapInvalido  # noqa: E402
from repositories import DocumentoSoapRepository, sessao  # noqa: E402

EXEMPLO = {
    "subjetivo": "Febre há três dias, dor no corpo e dor atrás dos olhos. Nega sangramentos.",
    "objetivo": "Temperatura 38,9 °C. PA 110x70 mmHg.",
    "avaliacao": "Quadro compatível com arbovirose, provável dengue sem sinais de alarme.",
    "plano": "Hidratação oral, dipirona se febre e retorno em 48 horas.",
    "hipoteses": [
        {"descricao": "Dengue sem sinais de alarme", "cid10": "A90", "confianca": "alta"},
        {"descricao": "Outra arbovirose", "cid10": None, "confianca": "baixa"},
    ],
    "alertas": ["Orientar sinais de alarme"],
    "pendencias": ["Hemograma"],
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("consultation_id")
    parser.add_argument("--arquivo", type=Path, help="JSON com as secoes (padrao: exemplo de dengue)")
    args = parser.parse_args(argv)
    versao = json.loads(args.arquivo.read_text(encoding="utf-8")) if args.arquivo else EXEMPLO
    try:
        documento = DocumentoSoapRepository(sessao.obter_sessao()).criar(
            args.consultation_id, versao, prompt_id="exemplo-dev", prompt_versao="0")
    except SoapInvalido as e:
        print(e)
        return 1
    finally:
        sessao.encerrar_sessao()
    if documento is None:
        print("Consulta nao encontrada.")
        return 1
    print(f"SOAP {documento['id']} criado na consulta {documento['consultation_id']} (status gerado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
