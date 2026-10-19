"""Repositorio de `documento_soap` (B39 / US018).

Nada entra na tabela sem passar pelo SoapV1: `criar` e `salvar_edicao`
validam o JSON e levantam SoapInvalido se ele estiver fora do esquema. Assim
o B40 (geracao pela IA) e o B43 (edicao pelo medico) gravam sempre o mesmo
formato, e o banco nunca guarda texto livre no lugar do SOAP.

Todo documento sai com `diff` (B44): a diferenca por secao entre a versao da
IA e a do medico, ou null enquanto o medico nao editou.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from backend.soap import VERSAO, validar_soap
from backend.soap.diff import calcular_diff
from models import Consulta, DocumentoSoap, StatusSoap

from .base import Repositorio, id_texto, iso, parse_uuid


class TransicaoInvalida(ValueError):
    """Operacao que o status atual do SOAP nao permite (ex.: editar aprovado)."""


def para_dicionario(doc: DocumentoSoap) -> dict:
    return {
        "id": id_texto(doc.id),
        "consultation_id": id_texto(doc.consulta_id),
        "status": doc.status.value,
        "schema_version": doc.schema_versao,
        "prompt": {"id": doc.prompt_id, "versao": doc.prompt_versao} if doc.prompt_id else None,
        "versao_ia": doc.versao_ia,
        "versao_medico": doc.versao_medico,
        # O que o medico ve e aprova: a edicao dele, ou a da IA se nao editou.
        "atual": doc.versao_medico or doc.versao_ia,
        "created_at": iso(doc.criado_em),
        "updated_at": iso(doc.atualizado_em),
        "approved_at": iso(doc.aprovado_em),
        "diff": calcular_diff(doc.versao_ia, doc.versao_medico),
    }


class DocumentoSoapRepository(Repositorio):
    def _obter_modelo(self, documento_id) -> DocumentoSoap | None:
        did = parse_uuid(documento_id)
        return self.sessao.get(DocumentoSoap, did) if did else None

    def obter(self, documento_id) -> dict | None:
        doc = self._obter_modelo(documento_id)
        return para_dicionario(doc) if doc else None

    def listar_da_consulta(self, consulta_id) -> list[dict]:
        """SOAPs da consulta, do mais recente para o mais antigo."""
        cid = parse_uuid(consulta_id)
        if cid is None:
            return []
        docs = self.sessao.scalars(
            select(DocumentoSoap)
            .where(DocumentoSoap.consulta_id == cid)
            .order_by(DocumentoSoap.criado_em.desc())
        )
        return [para_dicionario(d) for d in docs]

    def mais_recente(self, consulta_id) -> dict | None:
        """SOAP atual da consulta: cada geracao nova (B40) cria outro documento."""
        cid = parse_uuid(consulta_id)
        if cid is None:
            return None
        doc = self.sessao.scalar(
            select(DocumentoSoap)
            .where(DocumentoSoap.consulta_id == cid)
            .order_by(DocumentoSoap.criado_em.desc())
            .limit(1)
        )
        return para_dicionario(doc) if doc else None

    def criar(self, consulta_id, versao_ia, prompt_id=None, prompt_versao=None) -> dict | None:
        """Grava o SOAP gerado pela IA (status `gerado`). Valida pelo SoapV1
        (levanta SoapInvalido). Devolve None se a consulta nao existir."""
        soap = validar_soap(versao_ia)
        cid = parse_uuid(consulta_id)
        if cid is None or self.sessao.get(Consulta, cid) is None:
            return None
        doc = DocumentoSoap(
            consulta_id=cid,
            versao_ia=soap.model_dump(mode="json"),
            status=StatusSoap.GERADO,
            schema_versao=VERSAO,
            prompt_id=prompt_id,
            prompt_versao=prompt_versao,
        )
        self.sessao.add(doc)
        self.sessao.commit()
        return para_dicionario(doc)

    def salvar_edicao(self, documento_id, versao_medico) -> dict | None:
        """Grava a versao editada pelo medico (status `editado`); a versao da
        IA fica intacta para o diff (B44). Valida pelo SoapV1."""
        soap = validar_soap(versao_medico)
        doc = self._obter_modelo(documento_id)
        if doc is None:
            return None
        if doc.status in (StatusSoap.APROVADO, StatusSoap.INSERIDO_NO_PEP):
            raise TransicaoInvalida("SOAP aprovado nao pode mais ser editado.")
        doc.versao_medico = soap.model_dump(mode="json")
        doc.status = StatusSoap.EDITADO
        self.sessao.commit()
        return para_dicionario(doc)

    def aprovar(self, documento_id) -> dict | None:
        doc = self._obter_modelo(documento_id)
        if doc is None:
            return None
        if doc.status == StatusSoap.INSERIDO_NO_PEP:
            raise TransicaoInvalida("SOAP ja inserido no prontuario.")
        if doc.status != StatusSoap.APROVADO:
            doc.status = StatusSoap.APROVADO
            doc.aprovado_em = datetime.now(timezone.utc)
            self.sessao.commit()
        return para_dicionario(doc)
