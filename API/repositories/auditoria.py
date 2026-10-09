"""Repositorio da auditoria de envios externos (B36 / US016-CA004).

`registrar` NAO recebe conteudo - nem como argumento opcional. E de proposito:
sem parametro para texto, ninguem consegue, por descuido, gravar o que foi
enviado. Veja models/auditoria.py.
"""
from sqlalchemy import select

from models import Consulta, EnvioExterno, Medico

from .base import Repositorio, id_texto, iso, parse_uuid

# Provedores e operacoes conhecidos. Rotulos, nao enums: ver models/auditoria.py.
PROVEDOR_GEMINI = "gemini"
PROVEDOR_GOOGLE_SR = "google_sr"

OPERACAO_CHAT = "chat"
OPERACAO_EXTENSAO = "extensao"
OPERACAO_PDF = "pdf"
OPERACAO_RECOMENDACAO = "recomendacao"
OPERACAO_TRANSCRICAO = "transcricao"

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def envio_para_dicionario(envio: EnvioExterno) -> dict:
    return {
        "id": id_texto(envio.id),
        "created_at": iso(envio.criado_em),
        "consultation_id": id_texto(envio.consulta_id),
        "doctor_id": id_texto(envio.medico_id),
        "provider": envio.provedor,
        "operation": envio.operacao,
        "size_bytes": envio.tamanho_bytes,
        "calls": envio.chamadas,
    }


class AuditoriaEnvioRepository(Repositorio):
    def registrar(self, provedor, operacao, tamanho_bytes, consulta_id=None,
                  medico_id=None, chamadas=1) -> dict:
        # IDs que nao sao UUID, ou que nao existem no banco, viram None em vez de
        # violar a FK (Postgres) e derrubar o registro: perder a linha seria pior
        # que perder o vinculo. Mesmo criterio de PacienteRepository.criar para
        # `criado_por_id`.
        cid, mid = parse_uuid(consulta_id), parse_uuid(medico_id)
        if cid is not None and self.sessao.get(Consulta, cid) is None:
            cid = None
        if mid is not None and self.sessao.get(Medico, mid) is None:
            mid = None
        envio = EnvioExterno(
            consulta_id=cid,
            medico_id=mid,
            provedor=provedor,
            operacao=operacao,
            tamanho_bytes=max(0, int(tamanho_bytes)),
            chamadas=max(1, int(chamadas)),
        )
        self.sessao.add(envio)
        self.sessao.commit()
        return envio_para_dicionario(envio)

    def listar(self, consulta_id=None, limite=LIMITE_PADRAO) -> list[dict]:
        """Do mais recente para o mais antigo. `consulta_id` invalido => lista vazia."""
        consulta = select(EnvioExterno).order_by(EnvioExterno.criado_em.desc())
        if consulta_id is not None:
            cid = parse_uuid(consulta_id)
            if cid is None:
                return []
            consulta = consulta.where(EnvioExterno.consulta_id == cid)
        limite = max(1, min(int(limite), LIMITE_MAXIMO))
        return [envio_para_dicionario(e) for e in self.sessao.scalars(consulta.limit(limite))]
