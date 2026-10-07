"""Repositorios de `consulta` e `mensagem`.

As mensagens saem no formato que o front e o gemini_connection ja usam:
{"role": "user"|"model", "parts": [{"text": ...}], "timestamp": ...}.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models import Consulta, Mensagem, Paciente, PapelMensagem

from .base import Repositorio, como_utc, id_texto, iso, parse_data, parse_uuid

_UM_MICROSSEGUNDO = timedelta(microseconds=1)


def mensagem_para_dicionario(mensagem: Mensagem) -> dict:
    return {
        "role": mensagem.papel.value,
        "parts": [{"text": mensagem.conteudo_pseudonimizado}],
        "timestamp": iso(mensagem.ts),
    }


def _texto_da_mensagem(mensagem: dict) -> str:
    partes = mensagem.get("parts") or []
    return "".join(p.get("text", "") for p in partes if isinstance(p, dict))


class MensagemRepository(Repositorio):
    def historico(self, consulta_id) -> list[dict]:
        cid = parse_uuid(consulta_id)
        if cid is None:
            return []
        mensagens = self.sessao.scalars(
            select(Mensagem).where(Mensagem.consulta_id == cid).order_by(Mensagem.ts)
        )
        return [mensagem_para_dicionario(m) for m in mensagens]

    def adicionar(self, consulta_id, papel: str, texto: str) -> dict | None:
        cid = parse_uuid(consulta_id)
        if cid is None or self.sessao.get(Consulta, cid) is None:
            return None
        mensagem = Mensagem(
            consulta_id=cid,
            papel=PapelMensagem(papel),
            conteudo_pseudonimizado=texto or "",
            ts=self._proximo_ts(cid),
        )
        self.sessao.add(mensagem)
        self.sessao.commit()
        return mensagem_para_dicionario(mensagem)

    def _proximo_ts(self, consulta_id) -> datetime:
        # A ordem do chat vem de `ts`. O relogio do Windows pode repetir o
        # mesmo instante para a pergunta e a resposta gravadas em sequencia,
        # entao garantimos um ts estritamente crescente dentro da consulta.
        agora = datetime.now(timezone.utc)
        ultimo = self.sessao.scalar(
            select(func.max(Mensagem.ts)).where(Mensagem.consulta_id == consulta_id)
        )
        if ultimo is not None and como_utc(ultimo) >= agora:
            return como_utc(ultimo) + _UM_MICROSSEGUNDO
        return agora


class ConsultaRepository(Repositorio):
    def _paciente_id(self, paciente_id):
        pid = parse_uuid(paciente_id)
        if pid is None or self.sessao.get(Paciente, pid) is None:
            return None
        return pid

    def criar(self, paciente_id, titulo=None, data=None, historico_inicial=None) -> str | None:
        pid = self._paciente_id(paciente_id)
        if pid is None:
            return None
        paciente = self.sessao.get(Paciente, pid)
        agora = datetime.now(timezone.utc)
        consulta = Consulta(
            paciente_id=pid,
            medico_id=paciente.medico_id,
            titulo=titulo or f"Consulta em {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            inicio=parse_data(data) or agora,
        )
        self.sessao.add(consulta)
        self.sessao.flush()

        # Historico importado de consultas anteriores: grava na ordem recebida
        # com ts crescentes (o ts original de cada mensagem nao e preservado,
        # a ordem sim).
        for indice, mensagem in enumerate(historico_inicial or []):
            self.sessao.add(Mensagem(
                consulta_id=consulta.id,
                papel=PapelMensagem(mensagem.get("role", "model")),
                conteudo_pseudonimizado=_texto_da_mensagem(mensagem),
                ts=agora + indice * _UM_MICROSSEGUNDO,
            ))
        self.sessao.commit()
        return id_texto(consulta.id)

    def pertence_ao_paciente(self, paciente_id, consulta_id) -> bool:
        pid, cid = parse_uuid(paciente_id), parse_uuid(consulta_id)
        if pid is None or cid is None:
            return False
        consulta = self.sessao.get(Consulta, cid)
        return consulta is not None and consulta.paciente_id == pid

    def paciente_da_consulta(self, consulta_id) -> str | None:
        """Id do paciente dono da consulta (B07: a rota pep-import so recebe a consulta)."""
        cid = parse_uuid(consulta_id)
        consulta = self.sessao.get(Consulta, cid) if cid is not None else None
        return id_texto(consulta.paciente_id) if consulta is not None else None

    def listar(self, paciente_id) -> list[dict]:
        """Mais antiga primeiro (o chat e o upload de PDF usam a primeira)."""
        pid = parse_uuid(paciente_id)
        if pid is None:
            return []
        consultas = list(self.sessao.scalars(
            select(Consulta).where(Consulta.paciente_id == pid).order_by(Consulta.inicio)
        ))
        historicos = {c.id: [] for c in consultas}
        if consultas:
            mensagens = self.sessao.scalars(
                select(Mensagem)
                .where(Mensagem.consulta_id.in_(historicos))
                .order_by(Mensagem.ts)
            )
            for mensagem in mensagens:
                historicos[mensagem.consulta_id].append(mensagem_para_dicionario(mensagem))
        return [
            {
                "id": id_texto(c.id),
                "title": c.titulo,
                "date": iso(c.inicio),
                "chat_history": historicos[c.id],
            }
            for c in consultas
        ]
