"""Job diario que garante que nenhum audio fica no servidor (B35 / US017-CA007).

As rotas ja apagam o audio num `finally`, com ou sem sucesso na transcricao.
Este job cobre o que escapa delas:

- partes de gravacoes nunca finalizadas (navegador fechado no meio);
- arquivos sem linha no banco (processo derrubado entre gravar o arquivo e
  registrar a parte, ou durante a transcricao do audio inteiro).

Roda uma vez ao subir o servidor e depois a cada AUDIO_CLEANUP_INTERVAL_HOURS
(padrao 24 h). Tambem pode ser chamado por cron: `python scripts/limpar_audio.py`.
"""
import threading
from datetime import datetime, timedelta, timezone

from backend import audio_chunks
from backend.config import settings
from repositories import ParteAudioRepository, sessao


def limpar_audio_expirado(ttl_horas: float | None = None) -> dict:
    """Apaga partes e arquivos mais velhos que o prazo. Devolve as contagens
    (so numeros no log, nunca nome de paciente ou conteudo)."""
    ttl = settings.audio_chunk_ttl_hours if ttl_horas is None else ttl_horas
    limite = datetime.now(timezone.utc) - timedelta(hours=ttl)
    try:
        repo = ParteAudioRepository(sessao.obter_sessao())
        partes = repo.remover_anteriores_a(limite)
        audio_chunks.apagar(partes)
        orfaos = audio_chunks.apagar_orfaos(ttl * 3600, em_uso=repo.caminhos())
    finally:
        # Fora de uma requisicao ninguem chama o teardown do Flask
        sessao.encerrar_sessao()
    return {"partes_expiradas": len(partes), "arquivos_orfaos": len(orfaos)}


def _rodar_uma_vez() -> None:
    try:
        resultado = limpar_audio_expirado()
        if any(resultado.values()):
            print(f"[AUDIO] Limpeza: {resultado['partes_expiradas']} parte(s) expirada(s), "
                  f"{resultado['arquivos_orfaos']} arquivo(s) orfao(s) apagado(s).")
    except Exception as e:
        # Uma falha (banco fora do ar) nao pode matar a thread: tenta no proximo ciclo
        print(f"⚠️ [AUDIO] Limpeza falhou: {e}")


def iniciar_limpeza_periodica(intervalo_horas: float | None = None,
                              parar: threading.Event | None = None) -> threading.Thread | None:
    """Sobe a thread do job: limpa agora e depois a cada `intervalo_horas`.

    `intervalo_horas <= 0` desliga. `parar` encerra a thread (usado nos testes).
    """
    intervalo = settings.audio_cleanup_interval_hours if intervalo_horas is None else intervalo_horas
    if intervalo <= 0:
        return None
    parar = parar or threading.Event()

    def _laco():
        while not parar.is_set():
            _rodar_uma_vez()
            parar.wait(intervalo * 3600)

    thread = threading.Thread(target=_laco, name="limpeza-audio", daemon=True)
    thread.start()
    return thread
