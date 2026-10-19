"""Repositorio de `documento_soap`: versao da IA e versao do medico (B44).

`versao_ia` nunca muda depois de gravada: e a referencia do diff e da
auditoria do que o medico alterou. Cada geracao nova (B40) cria outro
documento; a consulta exibe o mais recente.
"""
from sqlalchemy import select

from backend.soap_diff import calcular_diff, validar_versao
from models import Consulta, DocumentoSoap, StatusSoap

from .base import Repositorio, iso, parse_uuid

# Depois de aprovado ou inserido no PEP, o texto e o que foi para o prontuario.
STATUS_FINAIS = (StatusSoap.APROVADO, StatusSoap.INSERIDO_NO_PEP)


class SoapNaoEditavel(Exception):
    """Documento ja aprovado ou inserido no PEP; vira 409 na rota."""


def soap_para_dicionario(doc: DocumentoSoap) -> dict:
    return {
        "id": str(doc.id),
        "consultation_id": str(doc.consulta_id),
        "status": doc.status.value,
        "versao_ia": doc.versao_ia,
        "versao_medico": doc.versao_medico,
        "created_at": iso(doc.criado_em),
        "approved_at": iso(doc.aprovado_em),
        "diff": calcular_diff(doc.versao_ia, doc.versao_medico),
    }


class SoapRepository(Repositorio):
    def _atual(self, consulta_id) -> DocumentoSoap | None:
        cid = parse_uuid(consulta_id)
        if cid is None:
            return None
        return self.sessao.scalar(
            select(DocumentoSoap)
            .where(DocumentoSoap.consulta_id == cid)
            .order_by(DocumentoSoap.criado_em.desc(), DocumentoSoap.id.desc())
            .limit(1)
        )

    def registrar_versao_ia(self, consulta_id, versao_ia: dict) -> dict | None:
        """Grava um SOAP recem-gerado (status `gerado`). None se a consulta nao
        existir. Ponto de entrada do gerador do B40."""
        cid = parse_uuid(consulta_id)
        if cid is None or self.sessao.get(Consulta, cid) is None:
            return None
        doc = DocumentoSoap(consulta_id=cid, versao_ia=validar_versao(versao_ia),
                            status=StatusSoap.GERADO)
        self.sessao.add(doc)
        self.sessao.commit()
        return soap_para_dicionario(doc)

    def atual(self, consulta_id) -> dict | None:
        doc = self._atual(consulta_id)
        return soap_para_dicionario(doc) if doc else None

    def salvar_versao_medico(self, consulta_id, versao_medico: dict) -> dict | None:
        """Grava a edicao do medico sobre o SOAP mais recente da consulta.

        O status vira `editado` quando ha diferenca para a IA; uma edicao que
        volta ao texto original devolve o status a `gerado`.
        """
        doc = self._atual(consulta_id)
        if doc is None:
            return None
        if doc.status in STATUS_FINAIS:
            raise SoapNaoEditavel(doc.status.value)
        versao = validar_versao(versao_medico)
        doc.versao_medico = versao
        alterado = calcular_diff(doc.versao_ia, versao)["alterado"]
        doc.status = StatusSoap.EDITADO if alterado else StatusSoap.GERADO
        self.sessao.commit()
        return soap_para_dicionario(doc)
