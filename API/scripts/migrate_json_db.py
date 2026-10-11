"""
Migra os bancos JSON antigos para o banco relacional (B21 / US015-CA003).

Le `patients_db.json` (pacientes, consultas, mensagens, dados da extensao,
transcricoes) e `users_db.json` (usuarios) e grava tudo nas tabelas do B19.
A aplicacao deixou de ler esses arquivos no B20; ate esta migracao rodar, o
que estava neles nao aparece no sistema.

Uso (dentro da pasta API; os caminhos padrao vem de PATIENTS_DB_FILE e
AUTH_USERS_DB_FILE, e o banco de DB_URL):

    python scripts/migrate_json_db.py --dry-run     # simula e mostra o relatorio
    python scripts/migrate_json_db.py               # migra de verdade

No Docker (os JSON ficam no volume backend_data):

    docker compose exec backend python scripts/migrate_json_db.py

Garantias:
- IDs preservados (a extensao guarda IDs de paciente/consulta); IDs que nao
  sao UUID viram um UUID deterministico (uuid5) e aparecem no relatorio.
- Hash de senha preservado: os usuarios entram com a mesma senha. A chave de
  cifra do B26 e criada no primeiro login, como para qualquer usuario antigo.
- Idempotente: o que ja existe no banco (mesmo ID ou mesmo e-mail) e pulado.
- Uma unica transacao; com --dry-run nada e gravado.
- Ao final, confere as contagens do JSON contra o banco e sai com codigo 1
  se algo nao foi migrado.

O paciente de demonstracao `paciente_abc` ("Joao Silva", recriado a cada
restart do servidor antigo) e descartado (decisao P11 / D-24), a menos que
se passe --manter-seed. O nome do paciente vai para `pseudonimo` no formato
sem cifra; o B26 so cifra linhas gravadas com a chave do medico em sessao.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from models import (  # noqa: E402
    ALGORITMO_SEM_CIFRA,
    Consulta,
    DadoExtensao,
    Medico,
    Mensagem,
    Paciente,
    PapelMensagem,
    Pseudonimo,
    StatusAprovacao,
    Transcricao,
)
from repositories.pacientes import NOME_PADRAO, novo_pseudonimo  # noqa: E402

SEED_ID = "paciente_abc"
# Namespace fixo: o mesmo ID antigo vira sempre o mesmo UUID (idempotencia).
NAMESPACE = uuid.UUID("6f0c2a52-3d1e-4b8e-9c55-b21b21b21b21")
TITULO_HISTORICO_LEGADO = "Histórico legado (chat do paciente)"
_UM_MICROSSEGUNDO = timedelta(microseconds=1)
_TIPOS_EXTENSAO = {"extracted_data", "pep_import"}


@dataclass
class Relatorio:
    origem: dict = field(default_factory=dict)      # contagens no JSON
    inseridos: dict = field(default_factory=dict)   # gravados agora
    existentes: dict = field(default_factory=dict)  # ja estavam no banco
    descartados: list = field(default_factory=list)
    ids_convertidos: dict = field(default_factory=dict)  # antigo -> novo
    avisos: list = field(default_factory=list)

    def soma(self, campo: str, chave: str, n: int = 1) -> None:
        alvo = getattr(self, campo)
        alvo[chave] = alvo.get(chave, 0) + n


# --- conversoes ------------------------------------------------------------

def _uuid(valor, *escopo, relatorio: Relatorio | None = None) -> uuid.UUID:
    """UUID original quando valido; senao uuid5 deterministico."""
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError):
        novo = uuid.uuid5(NAMESPACE, "/".join(map(str, (*escopo, valor))))
        if relatorio is not None:
            relatorio.ids_convertidos[str(valor)] = str(novo)
        return novo


def _data(valor) -> datetime | None:
    """ISO 8601 do JSON. Sem fuso e tratado como UTC, como a API faz (B20)."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        data = datetime.fromisoformat(valor.strip())
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=timezone.utc)


def _texto(mensagem: dict) -> str:
    partes = mensagem.get("parts") or []
    if isinstance(partes, str):
        return partes
    return "".join(p.get("text", "") for p in partes if isinstance(p, dict))


def _duracao(valor) -> float | None:
    """"2:05" (formato do transcription_log) ou numero -> segundos."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str) and ":" in valor:
        minutos, _, segundos = valor.partition(":")
        try:
            return int(minutos) * 60 + float(segundos)
        except ValueError:
            return None
    return None


def _lista(valor) -> list:
    return valor if isinstance(valor, list) else []


# --- usuarios ---------------------------------------------------------------

def migrar_usuarios(sessao: Session, usuarios: list[dict], rel: Relatorio) -> dict:
    """Grava os usuarios e devolve o mapa id antigo -> id no banco."""
    mapa: dict[str, uuid.UUID] = {}
    novos: list[tuple[Medico, dict]] = []
    rel.origem["usuarios"] = len(usuarios)

    for usuario in usuarios:
        id_antigo = str(usuario.get("id"))
        uid = _uuid(id_antigo, "usuario", relatorio=rel)
        email = (usuario.get("email") or "").strip().lower()

        existente = sessao.get(Medico, uid) or sessao.scalar(
            select(Medico).where(Medico.email == email)
        )
        if existente is not None:
            # Ex.: o admin do bootstrap ja criado pelo B20 com o mesmo e-mail.
            mapa[id_antigo] = existente.id
            rel.soma("existentes", "usuarios")
            continue

        status = usuario.get("approval_status")
        medico = Medico(
            id=uid,
            email=email,
            senha_hash=usuario.get("password_hash") or "!",
            nome=usuario.get("name") or email,
            crm=usuario.get("crm"),
            especialidade=usuario.get("specialty"),
            perfis=_lista(usuario.get("profiles")),
            ativo=bool(usuario.get("active", True)),
            status_aprovacao=StatusAprovacao(status) if status in {"pending", "approved", "rejected"} else None,
            aprovado_em=_data(usuario.get("approved_at")),
            rejeitado_em=_data(usuario.get("rejected_at")),
            motivo_rejeicao=usuario.get("rejection_reason"),
        )
        criado_em = _data(usuario.get("created_at"))
        if criado_em:
            medico.criado_em = criado_em
        if not usuario.get("password_hash"):
            rel.avisos.append(f"usuario {email}: sem password_hash; nao conseguira entrar.")
        sessao.add(medico)
        mapa[id_antigo] = uid
        novos.append((medico, usuario))
        rel.soma("inseridos", "usuarios")

    sessao.flush()
    # Segunda passada: quem aprovou/rejeitou pode ter vindo depois na lista.
    for medico, usuario in novos:
        medico.aprovado_por_id = mapa.get(str(usuario.get("approved_by")))
        medico.rejeitado_por_id = mapa.get(str(usuario.get("rejected_by")))
    return mapa


# --- pacientes e o que pertence a eles --------------------------------------

def _medico_do_registro(valor, mapa_usuarios: dict, rel: Relatorio, contexto: str):
    if not valor:
        return None
    medico_id = mapa_usuarios.get(str(valor))
    if medico_id is None:
        rel.avisos.append(f"{contexto}: usuario {valor} nao existe; ficou sem medico.")
    return medico_id


def _gravar_mensagens(sessao, consulta_id, historico, inicio, rel: Relatorio) -> None:
    anterior = None
    for mensagem in historico:
        papel = mensagem.get("role")
        if papel not in {"user", "model"}:
            rel.avisos.append(f"consulta {consulta_id}: mensagem com papel {papel!r} ignorada.")
            continue
        ts = _data(mensagem.get("timestamp")) or anterior or inicio
        # A ordem do chat vem de `ts`; mantem a ordem do JSON mesmo com
        # timestamps repetidos ou fora de ordem.
        if anterior is not None and ts <= anterior:
            ts = anterior + _UM_MICROSSEGUNDO
        sessao.add(Mensagem(
            consulta_id=consulta_id,
            papel=PapelMensagem(papel),
            conteudo_pseudonimizado=_texto(mensagem),
            ts=ts,
        ))
        anterior = ts
        rel.soma("inseridos", "mensagens")


def migrar_pacientes(sessao: Session, pacientes: dict, mapa_usuarios: dict,
                     rel: Relatorio, manter_seed: bool = False) -> None:
    agora = datetime.now(timezone.utc)
    for chave in ("pacientes", "consultas", "mensagens", "dados_extensao", "transcricoes"):
        rel.origem.setdefault(chave, 0)

    for id_antigo, registro in pacientes.items():
        if not isinstance(registro, dict):
            rel.avisos.append(f"paciente {id_antigo}: registro invalido, ignorado.")
            continue
        consultas = _lista(registro.get("consultations"))
        if id_antigo == SEED_ID and not manter_seed:
            rel.descartados.append(
                f"{SEED_ID} ({registro.get('name')}): seed de demonstracao, "
                f"{len(consultas)} consultas (P11 / D-24)"
            )
            continue

        chat_do_paciente = _lista(registro.get("chat_history"))
        extensao = _lista(registro.get("extension_data"))
        transcricoes = _lista(registro.get("transcription_log"))
        rel.origem["pacientes"] += 1
        rel.origem["consultas"] += len(consultas) + (1 if chat_do_paciente else 0)
        rel.origem["mensagens"] += sum(
            1 for c in consultas for m in _lista(c.get("chat_history"))
            if m.get("role") in {"user", "model"}
        ) + sum(1 for m in chat_do_paciente if m.get("role") in {"user", "model"})
        rel.origem["dados_extensao"] += len(extensao)
        rel.origem["transcricoes"] += len(transcricoes)

        pid = _uuid(id_antigo, "paciente", relatorio=rel)
        if sessao.get(Paciente, pid) is not None:
            rel.soma("existentes", "pacientes")
            continue

        medico_id = _medico_do_registro(registro.get("doctor_id"), mapa_usuarios, rel, f"paciente {id_antigo}")
        datas = [d for d in (_data(c.get("date")) for c in consultas) if d]
        criado_em = _data(registro.get("created_at")) or (min(datas) if datas else agora)

        paciente = Paciente(
            id=pid,
            medico_id=medico_id,
            criado_por_id=mapa_usuarios.get(str(registro.get("created_by"))),
            pseudonimo=novo_pseudonimo(pid),
            criado_em=criado_em,
        )
        paciente.dados_identificaveis = Pseudonimo(
            dados_cifrados=json.dumps({"nome": registro.get("name") or NOME_PADRAO}).encode("utf-8"),
            algoritmo_cifra=ALGORITMO_SEM_CIFRA,
        )
        sessao.add(paciente)
        sessao.flush()
        rel.soma("inseridos", "pacientes")

        mapa_consultas: dict[str, uuid.UUID] = {}
        for consulta in consultas:
            cid = _uuid(consulta.get("id"), "consulta", id_antigo, relatorio=rel)
            mapa_consultas[str(consulta.get("id"))] = cid
            inicio = _data(consulta.get("date")) or criado_em
            sessao.add(Consulta(
                id=cid, paciente_id=pid, medico_id=medico_id,
                titulo=(consulta.get("title") or f"Consulta em {inicio:%Y-%m-%d %H:%M}")[:200],
                inicio=inicio,
            ))
            sessao.flush()
            rel.soma("inseridos", "consultas")
            _gravar_mensagens(sessao, cid, _lista(consulta.get("chat_history")), inicio, rel)

        if chat_do_paciente:
            # Formato anterior as consultas: historico solto no paciente.
            inicio = _data(chat_do_paciente[0].get("timestamp")) or criado_em
            cid = uuid.uuid5(NAMESPACE, f"historico-legado/{id_antigo}")
            sessao.add(Consulta(id=cid, paciente_id=pid, medico_id=medico_id,
                                titulo=TITULO_HISTORICO_LEGADO, inicio=inicio))
            sessao.flush()
            rel.soma("inseridos", "consultas")
            _gravar_mensagens(sessao, cid, chat_do_paciente, inicio, rel)

        for item in extensao:
            tipo = item.get("type") if item.get("type") in _TIPOS_EXTENSAO else "extracted_data"
            sessao.add(DadoExtensao(
                id=_uuid(item.get("id") or uuid.uuid4(), "extensao", id_antigo),
                paciente_id=pid,
                consulta_id=mapa_consultas.get(str(item.get("consultation_id"))),
                url_origem=item.get("source_url"),
                conteudo=item.get("content") if item.get("content") is not None else {},
                tipo=tipo,
                pep_origem=item.get("pep_origem"),
                criado_em=_data(item.get("created_at") or item.get("timestamp")) or criado_em,
            ))
            rel.soma("inseridos", "dados_extensao")

        for item in transcricoes:
            sessao.add(Transcricao(
                id=_uuid(item.get("id") or uuid.uuid4(), "transcricao", id_antigo),
                paciente_id=pid,
                consulta_id=mapa_consultas.get(str(item.get("consultation_id"))),
                texto=item.get("text"),
                turnos=_lista(item.get("dialogue")),
                duracao_s=_duracao(item.get("duration")),
                provedor=item.get("source"),
                metadados_audio=item.get("audio") if isinstance(item.get("audio"), dict) else None,
                criado_em=_data(item.get("created_at") or item.get("timestamp")) or criado_em,
            ))
            rel.soma("inseridos", "transcricoes")
        sessao.flush()


# --- conferencia --------------------------------------------------------------

def conferir(sessao: Session, pacientes: dict, rel: Relatorio, manter_seed: bool = False) -> list[str]:
    """Compara, paciente a paciente, o JSON com o que esta no banco."""
    problemas = []
    for id_antigo, registro in pacientes.items():
        if not isinstance(registro, dict) or (id_antigo == SEED_ID and not manter_seed):
            continue
        pid = _uuid(id_antigo, "paciente")
        if sessao.get(Paciente, pid) is None:
            problemas.append(f"paciente {id_antigo} nao esta no banco")
            continue
        consultas = _lista(registro.get("consultations"))
        esperado_consultas = len(consultas) + (1 if _lista(registro.get("chat_history")) else 0)
        no_banco = sessao.scalars(select(Consulta.id).where(Consulta.paciente_id == pid)).all()
        if len(no_banco) < esperado_consultas:
            problemas.append(f"paciente {id_antigo}: {len(no_banco)} de {esperado_consultas} consultas")
        for consulta in consultas:
            cid = _uuid(consulta.get("id"), "consulta", id_antigo)
            esperado = sum(1 for m in _lista(consulta.get("chat_history")) if m.get("role") in {"user", "model"})
            gravado = len(sessao.scalars(select(Mensagem.id).where(Mensagem.consulta_id == cid)).all())
            if gravado < esperado:
                problemas.append(f"consulta {consulta.get('id')}: {gravado} de {esperado} mensagens")
        for nome, modelo, chave in (("dados da extensao", DadoExtensao, "extension_data"),
                                    ("transcricoes", Transcricao, "transcription_log")):
            esperado = len(_lista(registro.get(chave)))
            gravado = len(sessao.scalars(select(modelo.id).where(modelo.paciente_id == pid)).all())
            if gravado < esperado:
                problemas.append(f"paciente {id_antigo}: {gravado} de {esperado} {nome}")
    return problemas


def migrar(sessao: Session, pacientes: dict, usuarios: list[dict], manter_seed: bool = False) -> Relatorio:
    rel = Relatorio()
    mapa_usuarios = migrar_usuarios(sessao, usuarios, rel)
    migrar_pacientes(sessao, pacientes, mapa_usuarios, rel, manter_seed=manter_seed)
    return rel


# --- linha de comando ---------------------------------------------------------

def _carregar(caminho: Path, padrao):
    if not caminho.exists():
        print(f"[aviso] {caminho} nao existe; nada a migrar dele.")
        return padrao
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _imprimir(rel: Relatorio, simulacao: bool) -> None:
    prefixo = "[SIMULACAO] " if simulacao else ""
    print(f"\n{prefixo}Relatorio da migracao JSON -> banco")
    print(f"{'':16}{'no JSON':>9}{'inseridos':>11}{'ja existiam':>13}")
    for chave in ("usuarios", "pacientes", "consultas", "mensagens", "dados_extensao", "transcricoes"):
        print(f"{chave:16}{rel.origem.get(chave, 0):>9}{rel.inseridos.get(chave, 0):>11}"
              f"{rel.existentes.get(chave, '-'):>13}")
    for item in rel.descartados:
        print(f"descartado: {item}")
    for antigo, novo in rel.ids_convertidos.items():
        print(f"id convertido: {antigo} -> {novo}")
    for aviso in rel.avisos:
        print(f"aviso: {aviso}")


def main(argv=None) -> int:
    from backend.config import settings
    from repositories import sessao as sessao_db

    parser = argparse.ArgumentParser(description="Migra patients_db.json e users_db.json para o banco (B21).")
    parser.add_argument("--pacientes", type=Path, default=Path(settings.patients_db_file),
                        help="patients_db.json (padrao: PATIENTS_DB_FILE)")
    parser.add_argument("--usuarios", type=Path, default=Path(settings.auth_users_db_file),
                        help="users_db.json (padrao: AUTH_USERS_DB_FILE)")
    parser.add_argument("--db-url", help="banco de destino (padrao: DB_URL)")
    parser.add_argument("--dry-run", action="store_true", help="simula e desfaz tudo no fim")
    parser.add_argument("--manter-seed", action="store_true",
                        help=f"migra tambem o paciente de demonstracao {SEED_ID}")
    args = parser.parse_args(argv)

    pacientes = _carregar(args.pacientes, {})
    usuarios = _carregar(args.usuarios, {"users": []})
    if not isinstance(pacientes, dict) or not isinstance(usuarios, dict):
        print("Erro: formato inesperado (patients_db.json e users_db.json sao objetos JSON).")
        return 1

    sessao_db.aplicar_migracoes(args.db_url)
    sessao_db.configurar(args.db_url)
    sessao = sessao_db.obter_sessao()
    try:
        rel = migrar(sessao, pacientes, _lista(usuarios.get("users")), manter_seed=args.manter_seed)
        problemas = conferir(sessao, pacientes, rel, manter_seed=args.manter_seed)
        if args.dry_run or problemas:
            sessao.rollback()
        else:
            sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao_db.encerrar_sessao()

    _imprimir(rel, args.dry_run)
    if problemas:
        print("\nERRO: a conferencia encontrou diferencas; nada foi gravado.")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nConferencia: tudo o que estava no JSON esta no banco."
          + (" Nada foi gravado (dry-run)." if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
