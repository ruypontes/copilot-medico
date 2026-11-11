"""
Arquivo de configuracao do projeto Copilot Medico.
Carrega chaves e parametros do backend por variaveis de ambiente.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_PATH = Path(__file__).with_name(".env")
API_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    db_url: str = "sqlite:///app.db"
    app_title: str = "Copilot M\u00e9dico"
    gemini_api_key: str = ""

    # Modelo de linguagem do chat, do SOAP e das sugestoes. Claude e o padrao;
    # o Gemini (GEMINI_API_KEY) fica de reserva. LLM_PROVIDER=gemini inverte.
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-5-5"
    claude_effort: str = "high"

    auth_secret_key: str = ""
    auth_token_expiration_minutes: int = 15
    # Bancos JSON antigos (pre-B20). A aplicacao nao os le mais; ficam
    # configuraveis so para o script de migracao JSON -> banco do B21.
    auth_users_db_file: str = str(Path(__file__).with_name("users_db.json"))
    patients_db_file: str = str(Path(__file__).with_name("patients_db.json"))
    auth_bootstrap_email: str = ""
    auth_bootstrap_password: str = ""
    auth_bootstrap_name: str = "Administrador"
    auth_bootstrap_profiles: str = "administrador"

    # B22 - refresh token, politica de senha, rate limit e lockout no login.
    auth_refresh_token_expiration_days: int = 7
    auth_password_min_length: int = 8
    auth_login_rate_limit_attempts: int = 10
    auth_login_rate_limit_window_seconds: int = 300
    auth_login_lockout_attempts: int = 5
    auth_login_lockout_seconds: int = 900

    # Origens locais explicitas; configure CORS_ORIGINS no ambiente de producao.
    cors_origins: str = "http://localhost:8080,http://localhost:5174"

    # Partes (chunks) de audio da gravacao (B30). Ficam em disco so ate a
    # transcricao; vazio = pasta temporaria do sistema.
    audio_chunks_dir: str = ""
    audio_chunk_max_mb: int = 64
    # Partes de gravacoes nunca finalizadas sao apagadas depois deste prazo.
    audio_chunk_ttl_hours: int = 24
    # Job que apaga o audio que sobrou (B35); 0 desliga.
    audio_cleanup_interval_hours: float = 24

    # Provedor de transcricao (ADR-04). Vazio ou "whisper" usa o Whisper via
    # Groq com groq_api_key (padrao); sem essa chave, o Gemini audio (B31).
    # "gemini" forca o Gemini audio; "vosk" mantem so o Diarizador local.
    transcription_provider: str = ""
    gemini_audio_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_whisper_model: str = "whisper-large-v3"

    model_config = SettingsConfigDict(
        env_file=(str(API_ENV_PATH), str(BACKEND_ENV_PATH)),
        extra="ignore",
    )


settings = Settings()
