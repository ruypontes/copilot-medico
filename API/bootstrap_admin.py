import os
import sys

API_DIR = os.path.dirname(os.path.abspath(__file__))
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from backend.auth_service import bootstrap_users_if_needed
from backend.config import settings


def main() -> int:
    if not settings.auth_bootstrap_email or not settings.auth_bootstrap_password:
        print(
            "ERRO: configure AUTH_BOOTSTRAP_EMAIL e "
            "AUTH_BOOTSTRAP_PASSWORD antes de executar o bootstrap."
        )
        return 1

    try:
        # Usuarios ficam no banco desde o B20: garante as tabelas antes.
        from repositories import sessao

        sessao.aplicar_migracoes()
        bootstrap_users_if_needed()
    except Exception as exc:
        print(f"ERRO ao criar o administrador: {exc}")
        return 1

    print(f"Bootstrap do administrador concluído para: {settings.auth_bootstrap_email}")
    print("Se o administrador já existia, nenhum usuário duplicado foi criado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
