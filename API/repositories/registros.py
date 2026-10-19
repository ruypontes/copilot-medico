"""Repositorios de `transcricao` e `dado_extensao`: registros do paciente,
ligados ou nao a uma consulta. Listados do mais recente para o mais antigo,
como o transcription_log/extension_data do JSON.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from models import Consulta, DadoExtensao, Paciente, Transcricao

from .base import Repositorio, id_texto, iso, parse_data, parse_uuid


def _formatar_duracao(segundos: float | None) -> str:
    segundos = segundos or 0
    return f"{int(segundos // 60)}:{int(segundos % 60):02d}"


def transcricao_para_dicionario(t: Transcricao) -> dict:
    metadados = t.metadados_audio or {}
    criado_em = iso(t.criado_em)
    return {
        "id": id_texto(t.id),
        "patient_id": id_texto(t.paciente_id),
        "consultation_id": id_texto(t.consulta_id),
        "source": t.provedor,
        "type": "transcription",
        "text": t.texto,
        "dialogue": t.turnos or None,
        "duration": _formatar_duracao(t.duracao_s),
        "audio": metadados or {"persisted": False},
        "created_at": criado_em,
        "timestamp": criado_em,
    }


def dado_extensao_para_dicionario(d: DadoExtensao) -> dict:
    criado_em = iso(d.criado_em)
    item = {
        "id": id_texto(d.id),
        "patient_id": id_texto(d.paciente_id),
        "consultation_id": id_texto(d.consulta_id),
        "source": "extension",
        "source_url": d.url_origem,
        "type": d.tipo or "extracted_data",
        "content": d.conteudo,
        "created_at": criado_em,
        "timestamp": criado_em,
    }
    if d.pep_origem:
        item["pep_origem"] = d.pep_origem
    return item


class _RegistroDoPaciente(Repositorio):
    def _ids(self, paciente_id, consulta_id):
        """(paciente, consulta) validados; paciente None = nao encontrado."""
        pid = parse_uuid(paciente_id)
        if pid is None or self.sessao.get(Paciente, pid) is None:
            return None, None
        cid = parse_uuid(consulta_id)
        if cid is not None and self.sessao.get(Consulta, cid) is None:
            cid = None
        return pid, cid


class TranscricaoRepository(_RegistroDoPaciente):
    def adicionar(self, paciente_id, consulta_id, texto, duracao_s, turnos=None,
                  origem="extension", criado_em=None, metadados_audio=None) -> dict | None:
        pid, cid = self._ids(paciente_id, consulta_id)
        if pid is None:
            return None
        transcricao = Transcricao(
            paciente_id=pid,
            consulta_id=cid,
            texto=texto,
            turnos=turnos or [],
            duracao_s=duracao_s,
            # Ate existirem os provedores de transcricao (S3), `provedor`
            # guarda a origem do audio ("extension", ...), o antigo "source".
            provedor=origem,
            metadados_audio=metadados_audio if metadados_audio is not None else {"persisted": False},
            criado_em=parse_data(criado_em) or datetime.now(timezone.utc),
        )
        self.sessao.add(transcricao)
        self.sessao.commit()
        return transcricao_para_dicionario(transcricao)

    def listar(self, paciente_id) -> list[dict]:
        pid = parse_uuid(paciente_id)
        if pid is None:
            return []
        itens = self.sessao.scalars(
            select(Transcricao).where(Transcricao.paciente_id == pid)
            .order_by(Transcricao.criado_em.desc())
        )
        return [transcricao_para_dicionario(t) for t in itens]

    def listar_da_consulta_desde(self, consulta_id, desde: datetime) -> list[dict]:
        """Transcricoes da consulta gravadas a partir de `desde`, da mais
        antiga para a mais recente (janela das recomendacoes, B38)."""
        cid = parse_uuid(consulta_id)
        if cid is None:
            return []
        itens = self.sessao.scalars(
            select(Transcricao)
            .where(Transcricao.consulta_id == cid, Transcricao.criado_em >= desde)
            .order_by(Transcricao.criado_em)
        )
        return [transcricao_para_dicionario(t) for t in itens]


class DadoExtensaoRepository(_RegistroDoPaciente):
    def adicionar(self, paciente_id, conteudo, consulta_id=None, url_origem=None,
                  criado_em=None, tipo="extracted_data", pep_origem=None) -> dict | None:
        pid, cid = self._ids(paciente_id, consulta_id)
        if pid is None:
            return None
        dado = DadoExtensao(
            paciente_id=pid,
            consulta_id=cid,
            url_origem=url_origem,
            conteudo=conteudo,
            tipo=tipo,
            pep_origem=pep_origem,
            criado_em=parse_data(criado_em) or datetime.now(timezone.utc),
        )
        self.sessao.add(dado)
        self.sessao.commit()
        return dado_extensao_para_dicionario(dado)

    def listar(self, paciente_id) -> list[dict]:
        pid = parse_uuid(paciente_id)
        if pid is None:
            return []
        itens = self.sessao.scalars(
            select(DadoExtensao).where(DadoExtensao.paciente_id == pid)
            .order_by(DadoExtensao.criado_em.desc())
        )
        return [dado_extensao_para_dicionario(d) for d in itens]
