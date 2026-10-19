"""Chat da consulta: historico do banco + provedor de LLM (B41).

Mesma assinatura do antigo gemini_connection.send_message, usada pelas rotas
do server.py. Qualquer falha vira uma mensagem para o medico, como antes.
"""
from repositories import MensagemRepository, sessao

from .provider import LlmError, obter_provedor

MENSAGEM_ERRO = "Desculpe, ocorreu um erro ao tentar me comunicar com a inteligência artificial: {}"


def send_message(patient_id: str, consultation_id: str, message_text: str) -> str:
    try:
        provedor = obter_provedor()
        if provedor is None:
            raise LlmError("GEMINI_API_KEY não configurada")
        historico = MensagemRepository(sessao.obter_sessao()).historico(consultation_id)
        return provedor.enviar_mensagem(consultation_id, historico, message_text)
    except Exception as e:
        print(f"Erro ao enviar mensagem para a API Gemini para paciente {patient_id}, consulta {consultation_id}: {e}")
        return MENSAGEM_ERRO.format(e)
