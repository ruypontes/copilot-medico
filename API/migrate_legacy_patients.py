"""
Migração de pacientes sem médico (B68 / bug D-24 / decisão P11).

Atribui a um médico aprovado (o médico do piloto) todos os pacientes que
estão sem médico no banco e, por isso, invisíveis para qualquer médico.

Desde o B20 os pacientes ficam no banco relacional. O antigo paciente de
demonstração "paciente_abc" não chega ao banco (o ID não é UUID); o script de
migração do JSON (B21) é quem o descarta.

Uso (dentro da pasta API, com o venv ativo):

    python migrate_legacy_patients.py --list-doctors
    python migrate_legacy_patients.py --doctor-id <ID> --dry-run
    python migrate_legacy_patients.py --doctor-id <ID>
"""
import argparse
import sys


def get_approved_doctors():
    # Importado aqui dentro para que --help funcione sem carregar a configuração de autenticação.
    from backend.auth_service import list_doctor_requests

    return list_doctor_requests(status="approved")


def migrate_legacy_patients(doctor_id, dry_run=False):
    from repositories import PacienteRepository, sessao

    return PacienteRepository(sessao.obter_sessao()).atribuir_medico_aos_sem_medico(
        doctor_id, simular=dry_run
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Atribui um médico aos pacientes sem médico (bug D-24)."
    )
    parser.add_argument("--doctor-id", help="ID do médico que receberá os pacientes sem médico.")
    parser.add_argument(
        "--list-doctors",
        action="store_true",
        help="Lista os médicos aprovados e sai.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria feito, sem gravar nada.",
    )
    args = parser.parse_args(argv)

    doctors = get_approved_doctors()

    if args.list_doctors:
        if not doctors:
            print("Nenhum médico aprovado encontrado. Cadastre e aprove um médico primeiro.")
            return 1
        for doctor in doctors:
            print(f"{doctor['id']} | {doctor['name']} | {doctor['email']}")
        return 0

    if not args.doctor_id:
        parser.error("informe --doctor-id (use --list-doctors para ver os médicos aprovados).")

    if args.doctor_id not in {doctor["id"] for doctor in doctors}:
        print(f"Erro: {args.doctor_id} não é um médico aprovado. Use --list-doctors.")
        return 1

    assigned = migrate_legacy_patients(args.doctor_id, dry_run=args.dry_run)

    prefix = "[SIMULAÇÃO] " if args.dry_run else ""
    print(f"{prefix}Pacientes atribuídos ao médico {args.doctor_id}: {len(assigned)} {assigned}")
    if args.dry_run:
        print("Nada foi gravado (dry-run).")
    return 0


if __name__ == "__main__":
    from repositories import sessao

    sessao.aplicar_migracoes()
    sys.exit(main())
