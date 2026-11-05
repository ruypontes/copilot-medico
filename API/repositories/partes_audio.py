"""Repositorio de `parte_audio`: metadados das partes (chunks) de uma
gravacao que ainda nao foi transcrita (B30).

Os arquivos ficam em disco (backend/audio_chunks.py). Toda remocao devolve
os caminhos, para quem chama apagar os arquivos junto com as linhas.
"""
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from models import Consulta, ParteAudio

from .base import Repositorio, parse_uuid


def parte_para_dicionario(parte: ParteAudio) -> dict:
    return {
        "seq": parte.seq,
        "caminho": parte.caminho,
        "tamanho_bytes": parte.tamanho_bytes,
        "duracao_s": parte.duracao_s,
    }


class ParteAudioRepository(Repositorio):
    def _buscar(self, consulta_id, gravacao_id, seq) -> ParteAudio | None:
        return self.sessao.scalar(
            select(ParteAudio).where(
                ParteAudio.consulta_id == consulta_id,
                ParteAudio.gravacao_id == gravacao_id,
                ParteAudio.seq == seq,
            )
        )

    def registrar(self, consulta_id, gravacao_id, seq, caminho, tamanho_bytes,
                  duracao_s) -> tuple[dict | None, str | None]:
        """Registra a parte `seq` da gravacao.

        Um reenvio da mesma sequencia SUBSTITUI a parte anterior. Devolve
        (parte, caminho_substituido); a parte e None se a consulta nao existir.
        """
        cid = parse_uuid(consulta_id)
        if cid is None or self.sessao.get(Consulta, cid) is None:
            return None, None

        parte = self._buscar(cid, gravacao_id, seq)
        if parte is None:
            parte = ParteAudio(
                consulta_id=cid, gravacao_id=gravacao_id, seq=seq,
                caminho=caminho, tamanho_bytes=tamanho_bytes, duracao_s=duracao_s,
            )
            self.sessao.add(parte)
            try:
                self.sessao.commit()
                return parte_para_dicionario(parte), None
            except IntegrityError:
                # Dois envios simultaneos da mesma sequencia (o reenvio saiu
                # antes de o primeiro terminar): o segundo vira substituicao.
                self.sessao.rollback()
                parte = self._buscar(cid, gravacao_id, seq)
                if parte is None:
                    raise

        substituido = parte.caminho
        parte.caminho = caminho
        parte.tamanho_bytes = tamanho_bytes
        parte.duracao_s = duracao_s
        self.sessao.commit()
        return parte_para_dicionario(parte), substituido

    def listar(self, consulta_id, gravacao_id) -> list[dict]:
        """Partes recebidas da gravacao, em ordem de sequencia."""
        cid = parse_uuid(consulta_id)
        if cid is None:
            return []
        partes = self.sessao.scalars(
            select(ParteAudio)
            .where(ParteAudio.consulta_id == cid, ParteAudio.gravacao_id == gravacao_id)
            .order_by(ParteAudio.seq)
        )
        return [parte_para_dicionario(p) for p in partes]

    def remover(self, consulta_id, gravacao_id) -> list[str]:
        cid = parse_uuid(consulta_id)
        if cid is None:
            return []
        return self._remover(
            ParteAudio.consulta_id == cid, ParteAudio.gravacao_id == gravacao_id
        )

    def remover_anteriores_a(self, limite: datetime) -> list[str]:
        """Partes de gravacoes que nunca foram finalizadas (popup/navegador
        fechado no meio): o audio nao pode ficar esquecido no servidor."""
        return self._remover(ParteAudio.criado_em < limite)

    def caminhos(self) -> list[str]:
        """Arquivos que ainda tem linha (gravacao em andamento): o job de
        limpeza nao pode apaga-los como orfaos (B35)."""
        return list(self.sessao.scalars(select(ParteAudio.caminho)))

    def _remover(self, *filtros) -> list[str]:
        caminhos = list(self.sessao.scalars(select(ParteAudio.caminho).where(*filtros)))
        if caminhos:
            self.sessao.execute(delete(ParteAudio).where(*filtros))
            self.sessao.commit()
        return caminhos
