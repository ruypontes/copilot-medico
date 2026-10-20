"""Chat da consulta: historico do banco + provedor de LLM (B41).

Mesmas funcoes do antigo gemini_connection, usadas pelas rotas do server.py:
send_message (chat, PDF, PEP) transforma qualquer falha numa mensagem para o
medico, como antes; gerar_resposta_unica (recomendacoes do B38, SOAP do B40)
levanta.
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


def gerar_resposta_unica(instrucao: str, conteudo: str, response_schema: dict | None = None) -> str:
    """Uma chamada avulsa, SEM o historico do chat da consulta, pedindo JSON.

    Usada pelas recomendacoes (B38) e pela geracao do SOAP (B40); com
    `response_schema` (ADR-05) o Gemini segue a estrutura pedida. Diferente de
    send_message, levanta a excecao em caso de falha: quem chama decide a
    resposta HTTP.
    """
    provedor = obter_provedor()
    if provedor is None:
        raise LlmError("GEMINI_API_KEY não configurada")
    return provedor.gerar(conteudo, instrucao=instrucao, schema=response_schema, formato_json=True)
