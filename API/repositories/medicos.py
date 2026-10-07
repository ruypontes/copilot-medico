"""Repositorio da tabela `medico` (todos os usuarios: medicos e admins).

Substitui o users_db.json. Entra e sai no mesmo formato de dicionario que o
auth_service ja usava (id, email, name, password_hash, profiles, active,
crm, specialty, approval_status, approved_at/by, rejected_at/by,
rejection_reason, created_at), para que as regras de login, token e
aprovacao continuem iguais.
"""
from sqlalchemy import func, select

from models import Medico, StatusAprovacao

from .base import Repositorio, id_texto, iso, parse_data, parse_uuid

# chave do dicionario do auth_service -> coluna simples de `medico`
_CAMPOS_SIMPLES = {
    "email": "email",
    "name": "nome",
    "password_hash": "senha_hash",
    "crm": "crm",
    "specialty": "especialidade",
    "active": "ativo",
    "rejection_reason": "motivo_rejeicao",
}


def para_dicionario(medico: Medico) -> dict:
    return {
        "id": id_texto(medico.id),
        "email": medico.email,
        "name": medico.nome,
        "password_hash": medico.senha_hash,
        "profiles": list(medico.perfis or []),
        "active": medico.ativo,
        "created_at": iso(medico.criado_em),
        "crm": medico.crm,
        "specialty": medico.especialidade,
        "approval_status": medico.status_aprovacao.value if medico.status_aprovacao else None,
        "approved_at": iso(medico.aprovado_em),
        "approved_by": id_texto(medico.aprovado_por_id),
        "rejected_at": iso(medico.rejeitado_em),
        "rejected_by": id_texto(medico.rejeitado_por_id),
        "rejection_reason": medico.motivo_rejeicao,
    }


class MedicoRepository(Repositorio):
    def contar(self) -> int:
        return self.sessao.scalar(select(func.count()).select_from(Medico))

    def _por_id(self, user_id) -> Medico | None:
        uid = parse_uuid(user_id)
        return self.sessao.get(Medico, uid) if uid else None

    def existe(self, user_id) -> bool:
        return self._por_id(user_id) is not None

    def obter(self, user_id) -> dict | None:
        medico = self._por_id(user_id)
        return para_dicionario(medico) if medico else None

    def obter_por_email(self, email: str) -> dict | None:
        medico = self.sessao.scalar(select(Medico).where(Medico.email == email))
        return para_dicionario(medico) if medico else None

    def listar(self) -> list[dict]:
        medicos = self.sessao.scalars(select(Medico).order_by(Medico.criado_em))
        return [para_dicionario(m) for m in medicos]

    def criar(self, usuario: dict) -> dict:
        medico = Medico(perfis=list(usuario.get("profiles") or []))
        uid = parse_uuid(usuario.get("id"))
        if uid:
            medico.id = uid
        criado_em = parse_data(usuario.get("created_at"))
        if criado_em:
            medico.criado_em = criado_em
        self._aplicar(medico, usuario)
        self.sessao.add(medico)
        self.sessao.commit()
        return para_dicionario(medico)

    def atualizar(self, usuario: dict) -> dict | None:
        medico = self._por_id(usuario.get("id"))
        if medico is None:
            return None
        if "profiles" in usuario:
            medico.perfis = list(usuario["profiles"] or [])
        self._aplicar(medico, usuario)
        self.sessao.commit()
        return para_dicionario(medico)

    def _aplicar(self, medico: Medico, usuario: dict) -> None:
        for chave, coluna in _CAMPOS_SIMPLES.items():
            if chave in usuario:
                setattr(medico, coluna, usuario[chave])
        if "approval_status" in usuario:
            status = usuario["approval_status"]
            medico.status_aprovacao = StatusAprovacao(status) if status else None
        for chave, coluna in (("approved_at", "aprovado_em"), ("rejected_at", "rejeitado_em")):
            if chave in usuario:
                setattr(medico, coluna, parse_data(usuario[chave]))
        for chave, coluna in (("approved_by", "aprovado_por_id"), ("rejected_by", "rejeitado_por_id")):
            if chave in usuario:
                # So referencia quem existe na tabela (a FK exige).
                autor = self._por_id(usuario[chave])
                setattr(medico, coluna, autor.id if autor else None)
