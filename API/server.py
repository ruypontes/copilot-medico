import os
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, g, request, jsonify
from flask_cors import CORS
import tempfile
import speech_recognition as sr

# Assuming these imports are correct and available
from backend import audio_chunks
from backend import gemini_connection
from backend import pdf_reader
from backend import pep_import
from backend.anonimizacao import MapaAnonimizacao, anonimizar, anonimizar_estrutura
from backend.anonimizacao import servico as anonimizacao_servico
from backend.openapi import build_openapi_spec
from backend.pep_import import PepImportError
from backend.auth_decorators import roles_required, token_required
from backend.auth_service import (
    AuthError,
    authenticate_user,
    approve_doctor_request,
    check_account_lockout,
    check_login_rate_limit,
    create_access_token,
    create_doctor_registration,
    create_refresh_token,
    exchange_refresh_token,
    get_profile_details,
    is_valid_email,
    list_doctor_requests,
    normalize_email,
    normalize_profile,
    normalize_profiles,
    register_failed_login,
    register_login_attempt,
    reject_doctor_request,
    reset_login_lockout,
    sanitize_user,
    validate_user_profile_access,
)
from backend.config import settings

# Camada de dados (B20): um repositorio por entidade, no banco de DB_URL.
from repositories import (
    ConsultaRepository,
    DadoExtensaoRepository,
    MapaAnonimizacaoRepository,
    MedicoNaoEncontrado,
    MensagemRepository,
    PacienteRepository,
    ParteAudioRepository,
    TranscricaoRepository,
    sessao,
)
from backend.processador_voz.processador_voz import TranscritorVoz
from backend.audio_service import Diarizador
from backend.transcription import obter_provedor


def get_cors_origins():
    configured_origins = settings.cors_origins.strip()

    # Configuracao vazia ou "*" nao deve liberar todas as origens.
    if not configured_origins or configured_origins == "*":
        return []

    return [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]


app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": get_cors_origins()}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)


@app.teardown_appcontext
def _encerrar_sessao_do_banco(_exc):
    sessao.encerrar_sessao()


def _pacientes():
    return PacienteRepository(sessao.obter_sessao(), _cofre_atual())


def _consultas():
    return ConsultaRepository(sessao.obter_sessao())


def _mensagens():
    return MensagemRepository(sessao.obter_sessao())


def _transcricoes():
    return TranscricaoRepository(sessao.obter_sessao())


def _mapas_anonimizacao():
    return MapaAnonimizacaoRepository(sessao.obter_sessao())


def _partes_audio():
    return ParteAudioRepository(sessao.obter_sessao())


def _token_da_requisicao():
    """Token bruto do header; e a chave do cofre aberto nesta sessao (B26)."""
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.startswith("Bearer "):
        return None
    return cabecalho.removeprefix("Bearer ").strip() or None


def _cofre_atual():
    return anonimizacao_servico.cofre_da_sessao(_token_da_requisicao())


def _anonimizar_para_envio(texto, patient_id=None, consultation_id=None):
    """Prepara texto para sair da maquina e devolve (texto, mapa) (US016-CA001).

    O mapa da consulta e carregado antes e regravado depois, o que mantem os
    tokens estaveis entre mensagens (B25). Sem cofre aberto o mapa nao e
    persistido - a camada regex continua protegendo o payload, mas os tokens
    recomecam a cada requisicao.
    """
    cofre = _cofre_atual()
    mapa = _mapas_anonimizacao().carregar(consultation_id, cofre) if consultation_id else None

    paciente = _pacientes().obter(patient_id) if patient_id else None
    resultado = anonimizar(
        texto,
        mapa,
        nomes_conhecidos=anonimizacao_servico.nomes_do_cadastro(paciente),
    )

    if consultation_id:
        _mapas_anonimizacao().salvar(consultation_id, resultado.mapa, cofre)
    return resultado.texto, resultado.mapa


def _anonimizar_conteudo_extensao(conteudo, patient_id=None, consultation_id=None):
    """Anonimiza a estrutura raspada do prontuario antes de PERSISTI-LA (B69).

    `_anonimizar_para_envio` cobre o texto que sai para o LLM; este cobre o
    que fica no banco. Sao caminhos diferentes do mesmo dado: a estrutura vai
    para `dado_extensao.conteudo` e o texto formatado vai para `mensagem`.

    O mapa da consulta e carregado uma vez e reaproveitado em todos os campos,
    para que o mesmo CPF receba o mesmo token em toda a estrutura - e o mesmo
    token que a mensagem enviada ao modelo vai usar.
    """
    cofre = _cofre_atual()
    # Um unico mapa para TODOS os campos. Sem consulta ele comeca vazio em vez
    # de None: passar None faria `anonimizar` criar um mapa novo por campo, e
    # o mesmo CPF receberia tokens diferentes dentro da mesma estrutura.
    mapa = (
        _mapas_anonimizacao().carregar(consultation_id, cofre)
        if consultation_id
        else MapaAnonimizacao()
    )
    paciente = _pacientes().obter(patient_id) if patient_id else None
    nomes = anonimizacao_servico.nomes_do_cadastro(paciente)

    def _anonimizar_campo(texto):
        resultado = anonimizar(texto, mapa, nomes_conhecidos=nomes)
        return resultado.texto, resultado.mapa

    conteudo_anonimo, mapa_final = anonimizar_estrutura(conteudo, _anonimizar_campo)

    if consultation_id and mapa_final is not None:
        _mapas_anonimizacao().salvar(consultation_id, mapa_final, cofre)
    return conteudo_anonimo


def _dados_extensao():
    return DadoExtensaoRepository(sessao.obter_sessao())


audio_processor = None

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # Caminhos para os modelos dentro da pasta backend
    MODEL_PATH = os.path.join(BASE_DIR, "backend", "vosk-model-small-pt-0.3")
    SPK_MODEL_PATH = os.path.join(BASE_DIR, "backend", "vosk-model-spk-0.4")

    print("[SERVER] Carregando Modelos de IA...")

    # Inicializa a classe Diarizador (Vosk + Google)
    if os.path.exists(MODEL_PATH) and os.path.exists(SPK_MODEL_PATH):
        audio_processor = Diarizador(
            model_path=MODEL_PATH,
            spk_model_path=SPK_MODEL_PATH
        )
        print("✅ Diarizador Inteligente carregado com sucesso!")
    else:
        print(f"⚠️ Modelos não encontrados em: {MODEL_PATH}")
        print("   -> Baixe os modelos em https://alphacephei.com/vosk/models e extraia na pasta backend.")

except Exception as e:
    print(f"⚠️ AVISO: Falha ao carregar Diarizador: {e}")
    print("   -> O sistema funcionará apenas com Transcrição Simples.")
    audio_processor = None

# Provedor escolhido no .env (TRANSCRIPTION_PROVIDER); None = Diarizador acima.
transcription_provider = obter_provedor()
if transcription_provider:
    print(f"✅ Provedor de transcrição: {transcription_provider.nome}")


def _json_error(message, status_code):
    return jsonify({"status": "error", "message": message}), status_code


def current_user_is_admin():
    return getattr(g, "current_profile", "") == "administrador"


def current_user_is_doctor():
    return getattr(g, "current_profile", "") == "medico"


def patient_belongs_to_current_user(patient_id, patient_data=None):
    # `patient_data` evita uma segunda consulta ao banco quando quem chama ja
    # carregou o registro.
    if patient_data is None:
        patient_data = _pacientes().obter(patient_id)
    if not patient_data:
        return False
    if current_user_is_admin():
        return True
    if current_user_is_doctor():
        return patient_data.get("doctor_id") == g.current_user.get("id")
    return False


def require_patient_access(patient_id):
    patient_data = _pacientes().obter(patient_id)
    if not patient_data:
        return None, _json_error("Paciente nao encontrado.", 404)
    if not patient_belongs_to_current_user(patient_id, patient_data):
        return None, _json_error("Acesso negado ao paciente.", 403)
    return patient_data, None


def _patient_owner_for_new_record(data=None):
    if current_user_is_doctor():
        return g.current_user.get("id")
    if not isinstance(data, dict):
        return None
    doctor_id = data.get("doctor_id") or data.get("doctorId")
    return doctor_id.strip() if isinstance(doctor_id, str) and doctor_id.strip() else None


def _payload_value(data, *names):
    for name in names:
        if name in data:
            return data.get(name)
    return None


def _optional_text(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_extension_content(raw_content):
    if isinstance(raw_content, list):
        if not raw_content:
            return None, "extracted_content deve ser uma lista nao vazia."
        for index, item in enumerate(raw_content):
            if not isinstance(item, dict):
                return None, f"extracted_content[{index}] deve ser um objeto."
            role = item.get("role")
            text = item.get("text")
            if not isinstance(role, str) or not role.strip():
                return None, f"extracted_content[{index}].role e obrigatorio."
            if not isinstance(text, str) or not text.strip():
                return None, f"extracted_content[{index}].text e obrigatorio."
        return raw_content, None

    if isinstance(raw_content, dict) and raw_content:
        return raw_content, None

    if isinstance(raw_content, str) and raw_content.strip():
        return raw_content.strip(), None

    return None, "extracted_content deve ser uma lista nao vazia, objeto nao vazio ou texto."


def _normalize_transcriptions_for_extension_response(logs):
    normalized = []
    for log in logs:
        item = dict(log)
        item.setdefault("source", "extension")
        item.setdefault("type", "transcription")
        item.setdefault("created_at", item.get("timestamp"))
        item.setdefault("audio", {"persisted": False})
        normalized.append(item)
    return normalized


def _auth_success_response(user, profile, token, expires_in, refresh_token=None, refresh_expires_in=None):
    payload = {
        "status": "success",
        "token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "user": sanitize_user(user),
        "profile": get_profile_details(profile),
        "available_profiles": [
            get_profile_details(user_profile)
            for user_profile in normalize_profiles(user.get("profiles"))
        ],
    }
    if refresh_token is not None:
        payload["refresh_token"] = refresh_token
        payload["refresh_expires_in"] = refresh_expires_in
    return jsonify(payload), 200


def _format_extension_extracted_data(extracted_content, source_url=None):
    lines = ["Dados capturados da extensao Chrome"]

    if source_url:
        lines.extend(["", f"Fonte: {source_url}"])

    lines.append("")
    if isinstance(extracted_content, list):
        for item in extracted_content:
            lines.append(f"{item['role'].strip()}: {item['text'].strip()}")
    elif isinstance(extracted_content, dict):
        for key, value in extracted_content.items():
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            lines.append(f"{key}: {value}")
    else:
        lines.append(str(extracted_content))

    return "\n".join(lines)




@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Liveness/readiness sem autenticacao, consumido pelo HEALTHCHECK do Docker
    e pelo `depends_on: service_healthy` do compose (B12).

    Reporta tambem se a diarizacao subiu: os modelos Vosk sao baixados no build
    (B13) e sua ausencia degrada o servico sem derrubar o processo.
    """
    return jsonify({
        "status": "success",
        "service": "copilot-medico-api",
        "diarizer_loaded": audio_processor is not None,
    }), 200


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    email = normalize_email(data.get("email"))
    password = data.get("password")
    requested_profile = normalize_profile(data.get("profile"))

    if not email or password is None:
        return _json_error("Email e senha sao obrigatorios.", 400)
    if not is_valid_email(email):
        return _json_error("Email invalido.", 400)
    if not isinstance(password, str) or not password:
        return _json_error("Senha obrigatoria.", 400)
    if not requested_profile:
        return _json_error("Perfil e obrigatorio.", 400)

    client_ip = request.remote_addr or "unknown"
    try:
        check_login_rate_limit(client_ip)
        check_account_lockout(email)
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)

    user = authenticate_user(email, password, require_active=False)
    register_login_attempt(client_ip)
    if not user:
        register_failed_login(email)
        return _json_error("Email ou senha invalidos", 401)

    profiles = normalize_profiles(user.get("profiles"))
    if not profiles:
        return _json_error("Usuario sem perfil de acesso.", 403)

    try:
        validate_user_profile_access(user, requested_profile)
        token, expires_in = create_access_token(user, requested_profile)
        refresh_token, refresh_expires_in = create_refresh_token(user, requested_profile)
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)

    reset_login_lockout(email)

    # Cofre de cifra (B26): este e o unico momento em que a senha em claro
    # passa pelo servidor, logo o unico em que a DEK pode ser desembrulhada.
    # Dai em diante so a chave aberta vive em memoria, ate o logout.
    try:
        cofre = anonimizacao_servico.abrir_ou_criar_cofre(
            sessao.obter_sessao(), user.get("id"), password
        )
        anonimizacao_servico.registrar_sessao(token, cofre)
    except Exception as erro:
        # Falha de cifra nao pode impedir o login: a camada regex continua
        # protegendo o payload externo mesmo sem cofre.
        print(f"[ANONIMIZACAO] Nao foi possivel preparar o cofre do medico: {erro}")

    return _auth_success_response(
        user, requested_profile, token, expires_in, refresh_token, refresh_expires_in
    )


@app.route('/api/auth/refresh', methods=['POST'])
def refresh_token_route():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    refresh_token = data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return _json_error("refresh_token e obrigatorio.", 400)

    try:
        token, expires_in, _user = exchange_refresh_token(refresh_token)
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)

    # Cofre de cifra (B26): o cofre fica associado ao token de acesso antigo
    # (backend/anonimizacao/cofres.py). Se o cliente mandar o access token
    # antigo (mesmo expirado) no header Authorization, "mudamos" o cofre dele
    # para o token novo - sem isso, o medico perderia a cifra dos dados ate
    # logar de novo, so por ter renovado o access token.
    token_antigo = _token_da_requisicao()
    if token_antigo and token_antigo != token:
        cofre = anonimizacao_servico.cofre_da_sessao(token_antigo)
        if cofre is not None:
            anonimizacao_servico.registrar_sessao(token, cofre)
            anonimizacao_servico.encerrar_sessao(token_antigo)

    return jsonify({
        "status": "success",
        "token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }), 200


@app.route('/api/auth/logout', methods=['POST'])
@token_required
def logout():
    """Descarta a chave de dados da memoria (B26).

    Ate aqui o logout era so do lado do cliente, que apagava o token do
    chrome.storage. A DEK desembrulhada, porem, continuava no servidor ate
    o processo morrer. Esta rota fecha esse ciclo.
    """
    anonimizacao_servico.encerrar_sessao(_token_da_requisicao())
    return jsonify({"status": "success", "message": "Sessao encerrada."}), 200


@app.route('/api/auth/register-doctor', methods=['POST'])
def register_doctor():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    try:
        doctor = create_doctor_registration(
            name=data.get("name"),
            email=data.get("email"),
            password=data.get("password"),
            crm=data.get("crm"),
            specialty=data.get("specialty"),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "existe" in message else 400
        return _json_error(message, status_code)

    return jsonify({
        "status": "success",
        "message": "Cadastro enviado para aprovação do administrador.",
        "user": sanitize_user(doctor),
    }), 201


@app.route('/api/auth/select-profile', methods=['POST'])
@token_required
def select_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    selected_profile = normalize_profile(data.get("profile"))
    if not selected_profile:
        return _json_error("Perfil e obrigatorio.", 400)
    if selected_profile not in normalize_profiles(g.current_user.get("profiles")):
        return _json_error("Perfil nao permitido para este usuario.", 403)

    try:
        token, expires_in = create_access_token(g.current_user, selected_profile)
        refresh_token, refresh_expires_in = create_refresh_token(g.current_user, selected_profile)
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)

    # Cofre de cifra (B26): troca de perfil tambem gera um token novo - leva
    # o cofre aberto (se houver) do token antigo para o novo, pelo mesmo
    # motivo do /api/auth/refresh.
    token_antigo = _token_da_requisicao()
    if token_antigo and token_antigo != token:
        cofre = anonimizacao_servico.cofre_da_sessao(token_antigo)
        if cofre is not None:
            anonimizacao_servico.registrar_sessao(token, cofre)
            anonimizacao_servico.encerrar_sessao(token_antigo)

    return _auth_success_response(
        g.current_user, selected_profile, token, expires_in, refresh_token, refresh_expires_in
    )


@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_authenticated_user():
    profile = getattr(g, "current_profile", "")
    return jsonify({
        "status": "success",
        "user": getattr(g, "current_user_safe", {}),
        "profile": get_profile_details(profile),
        "available_profiles": [
            get_profile_details(user_profile)
            for user_profile in normalize_profiles(g.current_user.get("profiles"))
        ],
    }), 200


@app.route('/api/admin/doctor-requests', methods=['GET'])
@roles_required("administrador")
def get_doctor_requests_api():
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "all"}:
        return _json_error("Status invalido.", 400)
    return jsonify({
        "status": "success",
        "requests": list_doctor_requests(status),
    }), 200


@app.route('/api/admin/doctor-requests/<user_id>/approve', methods=['PATCH'])
@roles_required("administrador")
def approve_doctor_request_api(user_id):
    try:
        doctor = approve_doctor_request(user_id, g.current_user.get("id"))
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)
    return jsonify({
        "status": "success",
        "message": "Medico aprovado com sucesso.",
        "doctor": doctor,
    }), 200


@app.route('/api/admin/doctor-requests/<user_id>/reject', methods=['PATCH'])
@roles_required("administrador")
def reject_doctor_request_api(user_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)
    try:
        doctor = reject_doctor_request(user_id, g.current_user.get("id"), data.get("reason"))
    except AuthError as exc:
        return _json_error(exc.message, exc.status_code)
    return jsonify({
        "status": "success",
        "message": "Medico rejeitado.",
        "doctor": doctor,
    }), 200


# Respostas do transcritor para silencio/ruido: nao viram transcricao salva.
FRASES_DE_AUDIO_INVALIDO = (
    "Não foi possível entender o áudio",
    "Erro na API de reconhecimento",
)


def _transcrever_arquivo(caminho, duracao=0.0):
    """Transcreve um arquivo WAV e devolve (texto, turnos, duracao_s).

    Usa o provedor do .env (TRANSCRIPTION_PROVIDER, B32) ou a diarizacao
    (Vosk + Google) quando os modelos estao carregados e cai na transcricao simples, sem turnos, se ela falhar ou nao existir.
    Usado pela rota legada (audio inteiro) e pela transcricao por partes (B30).
    """
    # Provedor escolhido no .env (B32) ou Diarizador: mesmo contrato de retorno
    processador = transcription_provider or audio_processor
    if processador:
        try:
            print(f"[TRANSCRIÇÃO] Iniciando com {getattr(processador, 'nome', '') or 'Diarizador (Vosk + Google)'}...")
            result = processador.processar_audio(caminho)
            turnos = result['dialogue']  # Estrutura JSON rica (Médico/Paciente)
            # Sem duração informada, usa a do provedor ou o fim do último segmento
            if duracao == 0:
                duracao = result.get('duration') or 0
            if duracao == 0 and turnos:
                duracao = turnos[-1].get('end', 0)
            print("[TRANSCRIÇÃO] Diarização concluída com sucesso.")
            return result['full_text'], turnos, duracao
        except Exception as e:
            print(f"❌ Erro na Diarização: {e}. Tentando fallback simples...")

    print("[TRANSCRIÇÃO] Usando Transcritor Simples (Legacy)...")
    transcritor = TranscritorVoz(idioma="pt-BR")
    with sr.AudioFile(caminho) as source:
        audio_data = transcritor.reconhecedor.record(source)
        if duracao == 0:
            duracao = len(audio_data.frame_data) / audio_data.sample_rate / audio_data.sample_width
        return transcritor.transcrever(audio_data), None, duracao


@app.route('/api/transcribe_audio', methods=['POST'])
@roles_required("administrador", "medico")
def transcribe_audio_route():
    """
    Recebe áudio, faz Diarização (se disponível) ou Transcrição simples,
    salva no log e retorna o texto para o chat.
    """
    tmp_path = None
    try:
        # 1. Validação Básica
        if 'audio_file' not in request.files:
            return jsonify({"status": "error", "message": "Nenhum arquivo enviado."}), 400

        audio_file = request.files['audio_file']
        patient_id = request.form.get('patient_id') or request.form.get('patientId')
        consultation_id = request.form.get('consultation_id') or request.form.get('consultationId')
        # Duração estimada vinda do front (pode ser 0)
        duration_input = request.form.get('duration', 0.0, type=float)

        patient_id = patient_id.strip() if isinstance(patient_id, str) else None
        consultation_id = consultation_id.strip() if isinstance(consultation_id, str) and consultation_id.strip() else None

        if not patient_id:
            return jsonify({"status": "error", "message": "IDs obrigatórios."}), 400

        # 2. Salvar arquivo temporário
        patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error

        if consultation_id and not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return jsonify({"status": "error", "message": "Consulta nao encontrada para este paciente."}), 404

        file_ext = '.wav'
        if audio_file.filename and '.' in audio_file.filename:
            file_ext = '.' + audio_file.filename.split('.')[-1]

        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
            tmp_path = tmp.name
            audio_file.save(tmp_path)
            print(f"[TRANSCRIÇÃO] Áudio salvo em: {tmp_path}")

        # 3 e 4. Diarização inteligente ou, se falhar/não existir, transcrição simples
        texto_final, dialogue_structure, final_duration = _transcrever_arquivo(tmp_path, duration_input)

        # 5. Validação de Erro de Áudio (Silêncio/Ruído)
        if any(phrase in texto_final for phrase in FRASES_DE_AUDIO_INVALIDO):
            return jsonify({
                "status": "success",
                "transcription": texto_final,
                "is_error": True
            }), 200

        # 6. Salvar no Banco (Com o novo campo 'dialogue')
        log_entry = _transcricoes().adicionar(
            patient_id,
            consultation_id,
            texto=texto_final,
            duracao_s=final_duration if final_duration > 0 else 1.0,
            origem=request.form.get('source') or "extension",
            metadados_audio={
                "persisted": False,
                "filename": audio_file.filename,
                "content_type": audio_file.content_type,
            },
            turnos=dialogue_structure,  # Estrutura rica (Medico/Paciente) da diarizacao
        )

        return jsonify({
            "status": "success",
            "transcription": texto_final,
            "consultation_id": consultation_id,
            "log_entry": log_entry,  # O frontend vai receber isso e renderizar colorido
            "is_error": False
        }), 200

    except Exception as e:
        print(f"[TRANSCRIÇÃO] Erro 500: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro interno: {e}"}), 500
    finally:
        # Limpeza
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# Audio em partes (B30 / US017-CA003)
#
# A extensao grava a consulta e envia o audio em partes de ate 5 min, cada uma
# com a sua sequencia. As partes ficam em disco so ate a transcricao: ao parar,
# a extensao chama /transcribe, que junta o texto na ordem e apaga o audio.
# ---------------------------------------------------------------------------

def _consulta_da_gravacao(consultation_id):
    """(id da consulta normalizado, id do paciente, erro) das rotas de audio em partes."""
    patient_id = _consultas().paciente_da_consulta(consultation_id)
    if not patient_id:
        return None, None, _json_error("Consulta nao encontrada.", 404)
    _patient_data, access_error = require_patient_access(patient_id)
    if access_error:
        return None, None, access_error
    # O id vira nome de pasta em disco: usa a forma canonica do UUID.
    return str(uuid.UUID(consultation_id.strip())), patient_id, None


def _apagar_partes_esquecidas():
    """Gravacoes nunca finalizadas (navegador fechado no meio) nao podem
    deixar audio no servidor: apaga as partes mais velhas que o prazo."""
    limite = datetime.now(timezone.utc) - timedelta(hours=settings.audio_chunk_ttl_hours)
    audio_chunks.apagar(_partes_audio().remover_anteriores_a(limite))


@app.route('/api/consultations/<consultation_id>/audio/chunks', methods=['POST'])
@roles_required("administrador", "medico")
def upload_audio_chunk(consultation_id):
    """Recebe uma parte (WAV de ate 5 min) da gravacao da consulta.

    multipart: audio_file, recording_id (gerado pela extensao a cada gravacao)
    e seq (1, 2, 3...). Reenviar a mesma sequencia substitui a parte anterior,
    entao a extensao pode repetir o envio com seguranca quando ele falha.
    Responde 202: a parte fica guardada ate POST .../transcribe.
    """
    consulta_id, _patient_id, erro = _consulta_da_gravacao(consultation_id)
    if erro:
        return erro

    audio_file = request.files.get('audio_file')
    if audio_file is None:
        return _json_error("Nenhum arquivo enviado.", 400)

    try:
        recording_id = audio_chunks.validar_recording_id(request.form.get('recording_id'))
        seq = audio_chunks.validar_seq(request.form.get('seq'))
        arquivo = audio_chunks.salvar(audio_file, consulta_id, recording_id, seq)
    except audio_chunks.ParteInvalida as e:
        return _json_error(str(e), e.status)

    try:
        _apagar_partes_esquecidas()
        parte, caminho_substituido = _partes_audio().registrar(
            consulta_id, recording_id, seq,
            arquivo.caminho, arquivo.tamanho_bytes, arquivo.duracao_s,
        )
    except Exception:
        # Sem a linha no banco o arquivo ficaria orfao em disco.
        audio_chunks.apagar([arquivo.caminho])
        raise
    if caminho_substituido:
        audio_chunks.apagar([caminho_substituido])

    recebidas = [p["seq"] for p in _partes_audio().listar(consulta_id, recording_id)]
    # So metadados no log: nunca o conteudo do audio.
    print(f"[AUDIO] Parte {seq} da gravacao {recording_id} recebida "
          f"({parte['duracao_s']:.0f}s, {parte['tamanho_bytes']} bytes).")
    return jsonify({
        "status": "accepted",
        "consultation_id": consulta_id,
        "recording_id": recording_id,
        "seq": seq,
        "duration": parte["duracao_s"],
        "size_bytes": parte["tamanho_bytes"],
        "replaced": caminho_substituido is not None,
        "received": recebidas,
    }), 202


@app.route('/api/consultations/<consultation_id>/transcribe', methods=['POST'])
@roles_required("administrador", "medico")
def transcribe_recording(consultation_id):
    """Transcreve a gravacao enviada em partes e apaga o audio do servidor.

    JSON: recording_id e, opcionalmente, total_chunks (quantas partes a
    extensao gerou). As partes sao transcritas na ordem da sequencia. Uma parte
    que nao chegou ou que falha na transcricao NAO derruba a consulta: o texto
    sai com as demais e `chunks` informa o que faltou (missing/failed).
    A resposta tem o mesmo formato de /api/transcribe_audio.
    """
    consulta_id, patient_id, erro = _consulta_da_gravacao(consultation_id)
    if erro:
        return erro

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)
    try:
        recording_id = audio_chunks.validar_recording_id(data.get('recording_id'))
        total_chunks = data.get('total_chunks')
        if total_chunks is not None:
            total_chunks = audio_chunks.validar_seq(total_chunks, campo='total_chunks')
    except audio_chunks.ParteInvalida as e:
        return _json_error(str(e), e.status)

    partes = _partes_audio().listar(consulta_id, recording_id)
    if not partes:
        return _json_error("Nenhuma parte de audio recebida para esta gravacao.", 404)

    trechos = []  # (texto, turnos) das partes transcritas, em ordem
    falhas = []
    try:
        for parte in partes:
            try:
                texto, turnos, _duracao = _transcrever_arquivo(parte["caminho"], parte["duracao_s"])
            except Exception as e:
                print(f"[TRANSCRIÇÃO] Parte {parte['seq']} falhou: {e}")
                falhas.append(parte["seq"])
                continue
            if not texto or any(frase in texto for frase in FRASES_DE_AUDIO_INVALIDO):
                falhas.append(parte["seq"])  # silencio ou ruido
                continue
            trechos.append((texto, turnos))
    finally:
        # US017-CA007: o audio sai do servidor com ou sem sucesso na transcricao.
        audio_chunks.apagar(_partes_audio().remover(consulta_id, recording_id))

    recebidas = [parte["seq"] for parte in partes]
    esperadas = range(1, (total_chunks or recebidas[-1]) + 1)
    resumo = {
        "received": recebidas,
        "missing": [seq for seq in esperadas if seq not in recebidas],
        "failed": falhas,
    }
    resposta = {
        "status": "success",
        "consultation_id": consulta_id,
        "recording_id": recording_id,
        "chunks": resumo,
    }

    if not trechos:
        return jsonify({
            **resposta,
            "transcription": "Não foi possível entender o áudio.",
            "is_error": True,
        }), 200

    texto_final = "\n".join(texto for texto, _turnos in trechos)
    # Se alguma parte veio diarizada, as que vieram so com texto entram como um
    # turno sem papel definido, para nao sumirem do dialogo.
    dialogo = None
    if any(turnos for _texto, turnos in trechos):
        dialogo = []
        for texto, turnos in trechos:
            dialogo.extend(turnos or [{"role": "Outro", "role_key": "other", "text": texto}])

    log_entry = _transcricoes().adicionar(
        patient_id,
        consulta_id,
        texto=texto_final,
        duracao_s=sum(parte["duracao_s"] for parte in partes) or 1.0,
        origem="extension",
        metadados_audio={"persisted": False, "recording_id": recording_id, "chunks": resumo},
        turnos=dialogo,
    )
    return jsonify({
        **resposta,
        "transcription": texto_final,
        "log_entry": log_entry,
        "is_error": False,
    }), 200


# Rota para obter EXCLUSIVAMENTE o histórico de transcrições de áudio
@app.route('/api/patients/<patient_id>/transcription-log', methods=['GET'])
@roles_required("administrador", "medico")
def get_transcription_log_api(patient_id):
    try:
        _patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error
        logs = _transcricoes().listar(patient_id)
        return jsonify({
            "status": "success",
            "logs": logs,
            "count": len(logs)
        }), 200
    except Exception as e:
        print(f"Erro ao buscar logs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# NOVO ENDPOINT: Verificar existência do Patient ID
@app.route('/api/patient-exists/<patient_id>', methods=['GET'])
@roles_required("administrador", "medico")
def check_patient_exists_api(patient_id):
    """
    Verifica se um paciente com o ID fornecido existe no banco de dados.
    Retorna JSON com 'exists': true/false.
    """
    try:
        patient_data = _pacientes().obter(patient_id)
        exists = patient_data is not None
        if exists and not patient_belongs_to_current_user(patient_id, patient_data):
            return _json_error("Acesso negado ao paciente.", 403)
        return jsonify({"status": "success", "exists": exists}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro ao verificar existência do paciente: {e}"}), 500

# NOVO ENDPOINT: Criar Paciente
@app.route('/api/patients', methods=['POST'])
@roles_required("administrador", "medico")
def create_patient():
    """
    Cria um novo paciente e retorna seu ID e nome.
    Espera um JSON com 'name' (opcional).
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _json_error("Corpo JSON invalido.", 400)
        patient_name = data.get('name')
        doctor_id = _patient_owner_for_new_record(data)

        patient_data = _pacientes().criar(
            nome=patient_name,
            medico_id=doctor_id,
            criado_por_id=g.current_user.get("id"),
        )
        new_patient_id = patient_data["id"]

        # Adiciona a primeira "consulta" padrão ao criar o paciente
        first_consultation_id = _consultas().criar(new_patient_id, "Primeira Consulta")

        return jsonify({
            "status": "success",
            "patient_id": new_patient_id,
            "patient_name": patient_data.get("name", "Desconhecido"),
            "doctor_id": patient_data.get("doctor_id"),
            "first_consultation_id": first_consultation_id
        }), 201 # 201 Created

    except MedicoNaoEncontrado as e:
        return _json_error(str(e), 400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro interno do servidor ao criar paciente: {e}"}), 500


# Endpoint do Chat para usar o histórico da consulta selecionada
@app.route('/api/chat', methods=['POST'])
@roles_required("administrador", "medico")
def handle_chat_message():
    try:
        data = request.get_json(silent=True)
        if not data or 'message' not in data:
            return jsonify({"status": "error", "message": "Requisição inválida."}), 400

        user_message = data['message']
        patient_id = data.get('patient_id')
        consultation_id = data.get('consultation_id') # ID da consulta atual

        new_patient_id_generated = None

        if not patient_id: # Se não tem patient_id, cria um novo
            patient_id = _pacientes().criar(
                nome="Desconhecido",
                medico_id=_patient_owner_for_new_record(data),
                criado_por_id=g.current_user.get("id"),
            )["id"]
            new_patient_id_generated = patient_id

        # Se não tem consultation_id, ou se o paciente é novo, cria uma primeira consulta
        if patient_id and not new_patient_id_generated:
            _patient_data, access_error = require_patient_access(patient_id)
            if access_error:
                return access_error

        if not consultation_id:
            patient_consultations = _consultas().listar(patient_id)
            if patient_consultations:
                # Assumindo que a primeira consulta é a desejada. Você pode querer uma lógica de ordenação.
                consultation_id = patient_consultations[0]["id"] 
            else:
                consultation_id = _consultas().criar(patient_id, "Consulta Inicial (Chat)")
                if not consultation_id:
                    raise Exception("Falha ao criar consulta para o paciente.")

        if consultation_id and not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return _json_error("Consulta nao encontrada para este paciente.", 404)

        print(f"\nMensagem recebida para Paciente ID {patient_id}, Consulta ID {consultation_id}: {user_message}")

        # Anonimiza antes de qualquer saida (US016-CA001). O texto guardado
        # e o tokenizado: a coluna chama-se `conteudo_pseudonimizado`.
        # O fallback antigo ("se o filtro esvaziou, grava o original")
        # gravava PII justamente quando a anonimizacao era mais agressiva;
        # com tokens o texto nunca fica vazio, entao ele deixou de existir.
        texto_anonimo, mapa = _anonimizar_para_envio(
            user_message, patient_id, consultation_id
        )

        _mensagens().adicionar(consultation_id, "user", texto_anonimo)

        ai_response_text = gemini_connection.send_message(
            patient_id, consultation_id, texto_anonimo
        )

        # A resposta tambem fica tokenizada no banco; so a exibicao reidrata.
        _mensagens().adicionar(consultation_id, "model", ai_response_text)

        response_data = {
            "status": "success",
            # US016-CA002 / ADR-03: reidratado so aqui, na saida para o medico.
            "ai_response": mapa.reidratar(ai_response_text),
            "consultation_id": consultation_id
        }
        if new_patient_id_generated:
            response_data["patient_id"] = new_patient_id_generated

        return jsonify(response_data), 200

    except MedicoNaoEncontrado as e:
        return _json_error(str(e), 400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro interno do servidor: {e}"}), 500


def _register_pep_import(patient_id, consultation_id, data, require_typed=False):
    """Nucleo compartilhado das rotas de importacao do PEP (B07).

    Aceita o corpo tipado (`pep_origem` + `campos`) ou, nas rotas legadas, o formato
    livre (`extracted_content` / `extracted_data`). Em ambos a consulta e obrigatoria.
    """
    try:
        source_url = _payload_value(data, "source_url", "sourceUrl")
        created_at = _payload_value(data, "created_at", "createdAt")

        if not isinstance(patient_id, str) or not patient_id.strip():
            return _json_error("patient_id e obrigatorio.", 400)
        if not isinstance(consultation_id, str) or not consultation_id.strip():
            return _json_error("consultation_id e obrigatorio.", 400)
        if source_url is not None and not isinstance(source_url, str):
            return _json_error("source_url deve ser texto.", 400)
        if created_at is not None and not isinstance(created_at, str):
            return _json_error("created_at deve ser texto.", 400)

        typed = require_typed or "campos" in data
        normalized = None
        if typed:
            try:
                normalized = pep_import.parse_pep_import(data)
            except PepImportError as exc:
                return _json_error(str(exc), 400)
            extracted_content = normalized["campos"]
        else:
            raw_content = _payload_value(data, "extracted_content", "extractedData", "extracted_data")
            extracted_content, content_error = _normalize_extension_content(raw_content)
            if content_error:
                return _json_error(content_error, 400)

        patient_id = patient_id.strip()
        consultation_id = consultation_id.strip()
        source_url = _optional_text(source_url)
        created_at = _optional_text(created_at)

        _patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error

        if not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return _json_error("Consulta nao encontrada.", 404)

        # B69: a estrutura crua tambem e persistida, entao anonimizar apenas o
        # texto que vai ao LLM deixava nome e CPF em claro em `dado_extensao`.
        # O conteudo passa pelo anonimizador ANTES de ser gravado, usando o
        # mapa da consulta - assim o token de um CPF e o mesmo aqui e na
        # mensagem enviada ao modelo.
        conteudo_anonimo = _anonimizar_conteudo_extensao(
            extracted_content, patient_id, consultation_id
        )

        extension_entry = _dados_extensao().adicionar(
            patient_id,
            conteudo_anonimo,
            consulta_id=consultation_id,
            url_origem=source_url,
            criado_em=created_at,
            tipo="pep_import" if typed else "extracted_data",
            pep_origem=normalized["pep_origem"] if typed else None,
        )
        if not extension_entry:
            return _json_error("Falha ao salvar dados da extensao.", 500)

        if typed:
            formatted_text = pep_import.format_for_prompt(normalized, source_url)
        else:
            formatted_text = _format_extension_extracted_data(extracted_content, source_url)
        # Dado raspado do prontuario e o caminho mais provavel de PII
        # entrar no sistema: anonimiza antes de persistir ou enviar.
        texto_anonimo, mapa = _anonimizar_para_envio(
            formatted_text, patient_id, consultation_id
        )

        _mensagens().adicionar(consultation_id, "user", texto_anonimo)
        ai_response_text = gemini_connection.send_message(
            patient_id, consultation_id, texto_anonimo
        )
        _mensagens().adicionar(consultation_id, "model", ai_response_text)
        # Reidrata so o que volta para a tela do medico.
        ai_response_text = mapa.reidratar(ai_response_text)

        response = {
            "status": "success",
            "ai_response": ai_response_text,
            "patient_id": patient_id,
            "consultation_id": consultation_id,
            "extension_data": extension_entry,
        }
        if typed:
            response["resumo"] = pep_import.summarize(normalized)
        return jsonify(response), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro interno ao processar dados da extensao: {e}"}), 500


def _handle_extension_extracted_data_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    patient_id = _payload_value(data, "patient_id", "patientId")
    consultation_id = _payload_value(data, "consultation_id", "consultationId")
    return _register_pep_import(patient_id, consultation_id, data)


@app.route('/api/consultations/<consultation_id>/pep-import', methods=['POST'])
@roles_required("administrador", "medico")
def handle_pep_import(consultation_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Corpo JSON invalido.", 400)

    patient_id = _consultas().paciente_da_consulta(consultation_id)
    if not patient_id:
        return _json_error("Consulta nao encontrada.", 404)

    return _register_pep_import(patient_id, consultation_id, data, require_typed=True)


@app.route('/api/openapi.json', methods=['GET'])
def openapi_spec():
    return jsonify(build_openapi_spec())


@app.route('/api/extension/extracted-data', methods=['POST'])
@roles_required("administrador", "medico")
def handle_extension_extracted_data():
    return _handle_extension_extracted_data_request()


@app.route('/api/extracted-data', methods=['POST'])
@roles_required("administrador", "medico")
def handle_legacy_extracted_data():
    return _handle_extension_extracted_data_request()


@app.route('/api/patients/<patient_id>/extension-data', methods=['GET'])
@roles_required("administrador", "medico")
def get_patient_extension_data_api(patient_id):
    try:
        _patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error

        return jsonify({
            "status": "success",
            "patient_id": patient_id,
            "extension_data": _dados_extensao().listar(patient_id),
            "transcriptions": _normalize_transcriptions_for_extension_response(
                _transcricoes().listar(patient_id)
            )
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro ao recuperar dados da extensao: {e}"}), 500


# Endpoint de Upload de PDF
@app.route('/api/upload-pdf', methods=['POST'])
@roles_required("administrador", "medico")
def upload_pdf():
    try:
        if 'pdf' not in request.files:
            return jsonify({"status": "error", "message": "Nenhum arquivo enviado."}), 400

        file = request.files['pdf']
        patient_id = request.form.get('patient_id')
        consultation_id = request.form.get('consultation_id') # ID da consulta

        new_patient_id_generated = None

        if not patient_id:
            patient_id = _pacientes().criar(
                medico_id=_patient_owner_for_new_record({}),
                criado_por_id=g.current_user.get("id"),
            )["id"]
            new_patient_id_generated = patient_id
        else:
            _patient_data, access_error = require_patient_access(patient_id)
            if access_error:
                return access_error
        
        # Assegura que há uma consultation_id
        if not consultation_id:
            patient_consultations = _consultas().listar(patient_id)
            if patient_consultations:
                consultation_id = patient_consultations[0]["id"]
            else:
                consultation_id = _consultas().criar(patient_id, "Consulta de PDF")
                if not consultation_id:
                    raise Exception("Falha ao criar consulta para o paciente durante upload de PDF.")
        elif not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return _json_error("Consulta nao encontrada para este paciente.", 404)

        extracted_text = pdf_reader.extract_text_from_pdf(file)
        if not extracted_text.strip():
            return jsonify({"status": "error", "message": "Texto extraído está vazio."}), 400

        # PDF de exame costuma trazer nome, CPF e data de nascimento no
        # cabecalho: anonimiza antes de montar o contexto do modelo.
        texto_anonimo, mapa = _anonimizar_para_envio(
            extracted_text, patient_id, consultation_id
        )

        context_message_for_pdf = f"O seguinte texto foi extraído de um PDF enviado pelo usuário: \"{texto_anonimo}\". Por favor, analise-o e responda às perguntas subsequentes ou forneça um resumo, conforme apropriado."

        # Adiciona a mensagem ao histórico da consulta
        _mensagens().adicionar(consultation_id, "user", context_message_for_pdf)

        # A assinatura correta é send_message(patient_id: str, consultation_id: str, message_text: str)
        ai_response_text = gemini_connection.send_message(patient_id, consultation_id, context_message_for_pdf)

        # Adiciona a resposta da IA ao histórico da consulta
        _mensagens().adicionar(consultation_id, "model", ai_response_text)
        ai_response_text = mapa.reidratar(ai_response_text)

        response_data = {
            "status": "success",
            "message": "Texto extraído e enviado para a IA com sucesso.",
            "extracted_text_preview": extracted_text[:200] + "...",
            "ai_response": ai_response_text,
            "consultation_id": consultation_id
        }
        if new_patient_id_generated:
            response_data["patient_id"] = new_patient_id_generated
            
        return jsonify(response_data), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro interno ao processar o PDF: {e}"}), 500

## Rota `/api/patients/<patient_id>/consultations` para gerenciar consultas
@app.route('/api/patients/<patient_id>/consultations', methods=['GET', 'POST'])
@roles_required("administrador", "medico")
def handle_patient_consultations(patient_id):
    _patient_data, access_error = require_patient_access(patient_id)
    if access_error:
        return access_error

    if request.method == 'POST':
        # Lógica para CRIAR uma nova consulta
        try:
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                return _json_error("Corpo JSON invalido.", 400)
            consultation_title = data.get('title')
            import_consultation_ids = data.get('import_consultation_ids', [])

            if not consultation_title:
                consultation_title = f"Consulta em {datetime.now().strftime('%Y-%m-%d %H:%M')}"

            initial_history = []
            
            if import_consultation_ids and isinstance(import_consultation_ids, list) and len(import_consultation_ids) > 0:
                initial_history.append({
                    "role": "model",
                    "parts": [{"text": f"Históricos importados de consultas anteriores: {', '.join([c_id[:8] + '...' for c_id in import_consultation_ids])}."}],
                    "timestamp": datetime.now().isoformat()
                })

                for old_consultation_id in import_consultation_ids:
                    # So importa consultas do proprio paciente.
                    if not _consultas().pertence_ao_paciente(patient_id, old_consultation_id):
                        continue
                    old_history = _mensagens().historico(old_consultation_id)
                    if old_history:
                        initial_history.append({
                            "role": "model",
                            "parts": [{"text": f"--- Início do Histórico da Consulta {old_consultation_id[:8]}... ---"}],
                            "timestamp": datetime.now().isoformat()
                        })
                        initial_history.extend(old_history)
                        initial_history.append({
                            "role": "model",
                            "parts": [{"text": f"--- Fim do Histórico da Consulta {old_consultation_id[:8]}... ---"}],
                            "timestamp": datetime.now().isoformat()
                        })
            
            # Chama a função para adicionar a nova consulta com o histórico inicial (se houver)
            new_consultation_id = _consultas().criar(patient_id, consultation_title, historico_inicial=initial_history)

            if new_consultation_id:
                return jsonify({
                    "status": "success",
                    "message": "Consulta criada com sucesso.",
                    "consultation_id": new_consultation_id,
                    "consultation_title": consultation_title
                }), 201
            else:
                return jsonify({"status": "error", "message": "Falha ao criar nova consulta no banco de dados."}), 500

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Erro interno ao criar consulta: {e}"}), 500

    elif request.method == 'GET':
        # Lógica para OBTER a lista de consultas
        try:
            consultations = _consultas().listar(patient_id)
            return jsonify({"status": "success", "consultations": consultations}), 200
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Erro ao recuperar consultas do paciente: {e}"}), 500
        
# NOVO ENDPOINT: Obter Histórico de uma Consulta Específica
@app.route('/api/patients/<patient_id>/consultations/<consultation_id>/history', methods=['GET'])
@roles_required("administrador", "medico")
def get_consultation_history_api(patient_id, consultation_id):
    """
    Retorna o histórico de chat de uma consulta específica.
    """
    try:
        _patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error
        if not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return _json_error("Consulta nao encontrada para este paciente.", 404)
        history = _mensagens().historico(consultation_id)
        if history is not None:
            return jsonify({"status": "success", "history": history}), 200
        else:
            return jsonify({"status": "error", "message": "Histórico da consulta não encontrado."}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Erro ao recuperar histórico da consulta: {e}"}), 500
    
@app.route('/api/all-patients', methods=['GET'])
@roles_required("administrador", "medico")
def get_all_patients():
    """
    Retorna uma lista de todos os pacientes (ID e Nome) para o frontend.
    """
    try:
        if current_user_is_admin():
            patients_info = _pacientes().listar()
        else:
            patients_info = _pacientes().listar(medico_id=g.current_user.get("id"))
        return jsonify({"status": "success", "patients": patients_info}), 200
    except Exception as e:
        import traceback
        traceback.print_exc() 
        return jsonify({"status": "error", "message": f"Erro ao obter lista de pacientes: {e}"}), 500

@app.route('/api/recommendations', methods=['POST'])
@roles_required("administrador", "medico")
def handle_recommendations():
    """
    Endpoint para solicitação de recomendações com base no andamento/histórico da consulta.
    """
    try:

        data = request.get_json()

        # Verifica se o JSON existe
        if not data:
            return jsonify({"error": "Requisição inválida. Corpo JSON esperado."}), 400

        # Verifica se o patient_id e o consultation_id estão presentes no JSON
        patient_id = data.get('patient_id')
        consultation_id = data.get('consultation_id')

        if not patient_id or not consultation_id:
            return jsonify({"error": "paciente_id e consulta_id não encontrados."}), 400

        # Define o caminho para o arquivo do prompt de recomendações
        _patient_data, access_error = require_patient_access(patient_id)
        if access_error:
            return access_error
        if not _consultas().pertence_ao_paciente(patient_id, consultation_id):
            return _json_error("Consulta nao encontrada para este paciente.", 404)

        prompt_file_path = os.path.join(os.path.dirname(__file__), 'recommendations.txt')

        # Verifica se o arquivo existe
        if not os.path.exists(prompt_file_path):
            raise FileNotFoundError(f"Arquivo de prompt não encontrado em: {prompt_file_path}")

        # Lê o conteúdo do arquivo
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            prompt_recomendacao_medica = f.read()

        if not prompt_recomendacao_medica:
            raise ValueError(f"O arquivo de prompt {prompt_file_path} está vazio.")

        print(f"[RECOMENDAÇÃO] Iniciando busca para consulta_id: {consultation_id}")

        # Chama a API Gemini. Ela carrega o histórico (incluindo transcrições) e
        # recebe o prompt de recomendação.
        resposta_ia = gemini_connection.send_message(
            patient_id,
            consultation_id,
            prompt_recomendacao_medica
        )

        # Retornar a recomendação para o frontend
        return jsonify({"status": "success", "recommendation": resposta_ia}), 200

    except Exception as e:
        print(f"Erro catastrófico no endpoint /get_recommendation: {e}")
        return jsonify({"error": f"Erro interno do servidor: {str(e)}"}), 500



if __name__ == '__main__':
    # Cria/atualiza as tabelas antes de subir (alembic upgrade head), no
    # Docker e fora dele. O antigo seed do "Joao Silva" (D-09/D-24) saiu.
    sessao.aplicar_migracoes()
    print("Servidor Flask com Gemini e banco relacional iniciado.")
    app.run(host='0.0.0.0', port=3001, debug=True)
