"""Apaga o audio que sobrou no servidor (B35 / US017-CA007).

O servidor ja roda esta limpeza ao subir e a cada AUDIO_CLEANUP_INTERVAL_HOURS.
Este script e para rodar fora dele (cron, Agendador de Tarefas) ou na hora:

    python scripts/limpar_audio.py                 # prazo de AUDIO_CHUNK_TTL_HOURS
    python scripts/limpar_audio.py --ttl-horas 0   # tudo que nao esta em uso

No Docker:

    docker compose exec backend python scripts/limpar_audio.py
"""
import argparse
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from backend.limpeza_audio import limpar_audio_expirado  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ttl-horas", type=float, default=None,
                        help="apaga o que for mais velho que isto (padrao: AUDIO_CHUNK_TTL_HOURS)")
    args = parser.parse_args(argv)
    resultado = limpar_audio_expirado(args.ttl_horas)
    print(f"Partes expiradas: {resultado['partes_expiradas']}; "
          f"arquivos orfaos: {resultado['arquivos_orfaos']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
