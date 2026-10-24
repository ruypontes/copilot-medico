import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt
from werkzeug.security import check_password_hash, generate_password_hash

from repositories import MedicoRepository, sessao

from .config import settings


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PROFILE_ALIASES = {
    "admin": "administrador",
    "administrador": "administrador",
    "administrator": "administrador",
    "medico": "medico",
    "m\u00e9dico": "medico",
    "doctor": "medico",
    "recepcao": "recepcao",
    "recep\u00e7\u00e3o": "recepcao",
    "reception": "recepcao",
    "usuario": "usuario",
    "usu\u00e1rio": "usuario",
    "user": "usuario",
}

PROFILE_REDIRECTS = {
    "administrador": "/admin",
    "medico": "/medico",
    "recepcao": "/recepcao",
    "usuario": "/app",
}

PROFILE_PERMISSIONS = {
    "administrador": {
        "admin:read",
        "admin:write",
        "patients:read",
        "patients:write",
        "consultations:read",
        "consultations:write",
        "chat:use",
        "pdf:upload",
        "audio:transcribe",
        "recommendations:read",
        "profiles:select",
    },
    "medico": {
        "patients:read",
        "patients:write",
        "consultations:read",
        "consultations:write",
        "chat:use",
        "pdf:upload",
        "audio:transcribe",
        "recommendations:read",
        "profiles:select",
    },
    "recepcao": {
        "patients:read",
        "patients:write",
        "consultations:read",
        "consultations:write",
        "profiles:select",
    },
    "usuario": {
        "patients:read",
        "consultations:read",
        "profiles:select",
    },
}


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_password_policy(password: Any) -> None:
    """Levanta ValueError se a senha nao atender a politica minima (B22).

    Nao mexe em como a senha e guardada (continua werkzeug/scrypt) - so valida
    o texto da senha antes de gerar o hash.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("Senha obrigatoria")
    if len(password) < settings.auth_password_min_length:
        raise ValueError(
            f"Senha deve ter pelo menos {settings.auth_password_min_length} caracteres"
        )
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Senha deve conter pelo menos uma letra")
    if not re.search(r"\d", password):
        raise ValueError("Senha deve conter pelo menos um numero")


# --- Rate limit e lockout do login (B22 / D-26) ---------------------------
# Implementacao em memoria (reinicia quando o servidor reinicia). Suficiente
# para o escopo deste ticket; se no futuro houver varias instancias do
# backend rodando ao mesmo tempo, isso precisaria virar um armazenamento
# compartilhado (ex. Redis).
_rate_limit_lock = threading.Lock()
_login_attempts_by_ip: dict[str, list[float]] = {}
_lockouts_by_email: dict[str, dict[str, Any]] = {}


def check_login_rate_limit(ip: str) -> None:
    now = _utcnow().timestamp()
    window = settings.auth_login_rate_limit_window_seconds
    max_attempts = settings.auth_login_rate_limit_attempts
    with _rate_limit_lock:
        attempts = [t for t in _login_attempts_by_ip.get(ip or "unknown", []) if now - t < window]
        _login_attempts_by_ip[ip or "unknown"] = attempts
        if len(attempts) >= max_attempts:
            raise AuthError(
                "Muitas tentativas de login a partir deste endereco. Tente novamente mais tarde.",
                429,
            )


def register_login_attempt(ip: str) -> None:
    now = _utcnow().timestamp()
    with _rate_limit_lock:
        _login_attempts_by_ip.setdefault(ip or "unknown", []).append(now)



def check_account_lockout(email: str) -> None:
    normalized_email = normalize_email(email)
    with _rate_limit_lock:
        record = _lockouts_by_email.get(normalized_email)
        if record is None:
            return

        locked_until = record.get("locked_until", 0)
        if locked_until > _utcnow().timestamp():
            raise AuthError(
                "Conta temporariamente bloqueada por excesso de tentativas. Tente novamente mais tarde.",
                403,
            )
        if locked_until:
            # O bloqueio ja passou (locked_until > 0, mas no passado):
            # descarta o registro antigo, senao o contador de falhas
            # continuaria acumulado e uma unica tentativa errada depois do
            # prazo re-bloquearia a conta na hora. Um registro com
            # locked_until == 0 so significa "ainda nao bateu o limite de
            # falhas" - esse continua acumulando normalmente.
            _lockouts_by_email.pop(normalized_email, None)



def register_failed_login(email: str) -> None:
    normalized_email = normalize_email(email)
    now = _utcnow().timestamp()
    with _rate_limit_lock:
        record = _lockouts_by_email.setdefault(normalized_email, {"failed": 0, "locked_until": 0})
        record["failed"] += 1
        if record["failed"] >= settings.auth_login_lockout_attempts:
            record["locked_until"] = now + settings.auth_login_lockout_seconds


def reset_login_lockout(email: str) -> None:
    normalized_email = normalize_email(email)
    with _rate_limit_lock:
        _lockouts_by_email.pop(normalized_email, None)

def get_auth_secret() -> str:
    if settings.auth_secret_key:
        return settings.auth_secret_key
    raise AuthError("AUTH_SECRET_KEY nao configurado", 401)


def normalize_email(email: Any) -> str:
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email))


def normalize_profile(profile: Any) -> str:
    if not isinstance(profile, str):
        return ""
    cleaned = profile.strip().lower()
    return PROFILE_ALIASES.get(cleaned, cleaned)


def normalize_profiles(profiles: list[str] | str | None) -> list[str]:
    if isinstance(profiles, str):
        raw_profiles = [item.strip() for item in profiles.split(",")]
    elif isinstance(profiles, list):
        raw_profiles = profiles
    else:
        raw_profiles = []

    normalized: list[str] = []
    for profile in raw_profiles:
        value = normalize_profile(profile)
        if value in PROFILE_PERMISSIONS and value not in normalized:
            normalized.append(value)
    return normalized


def _medicos() -> MedicoRepository:
    # Usuarios ficam na tabela `medico` (B20); o users_db.json so e lido pelo
    # script de migracao do B21.
    return MedicoRepository(sessao.obter_sessao())


def bootstrap_users_if_needed() -> None:
    if _medicos().contar() > 0:
        return

    email = normalize_email(settings.auth_bootstrap_email)
    password = settings.auth_bootstrap_password
    if not email or not password:
        return

    profiles = normalize_profiles(settings.auth_bootstrap_profiles)
    if not profiles:
        profiles = ["administrador"]

    try:
        create_user(email, password, settings.auth_bootstrap_name, profiles)
    except ValueError as exc:
        # Nao derruba o servidor por causa de uma senha de bootstrap antiga
        # que nao segue mais a politica (B22). So avisa no log.
        print(f"[AUTH] Nao foi possivel criar o usuario de bootstrap: {exc}")


def create_user(
    email: str,
    password: str,
    name: str,
    profiles: list[str],
    *,
    active: bool = True,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    email = normalize_email(email)
    if not is_valid_email(email):
        raise ValueError("Email invalido")
    validate_password_policy(password)

    normalized_profiles = normalize_profiles(profiles)
    if not normalized_profiles:
        raise ValueError("Perfil invalido")

    if _medicos().obter_por_email(email) is not None:
        raise ValueError("Usuario ja existe")

    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": name or email,
        "password_hash": generate_password_hash(password),
        "profiles": normalized_profiles,
        "active": active,
        "created_at": _utcnow().isoformat(),
    }
    if extra_fields:
        user.update(extra_fields)
    return _medicos().criar(user)


def create_doctor_registration(
    *,
    name: Any,
    email: Any,
    password: Any,
    crm: Any = None,
    specialty: Any = None,
) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Nome obrigatorio")
    if not is_valid_email(normalized_email):
        raise ValueError("Email invalido")
    if not isinstance(password, str) or not password:
        raise ValueError("Senha obrigatoria")

    extra_fields = {
        "crm": crm.strip() if isinstance(crm, str) and crm.strip() else None,
        "specialty": specialty.strip() if isinstance(specialty, str) and specialty.strip() else None,
        "approval_status": "pending",
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
    }
    return create_user(
        normalized_email,
        password,
        name.strip(),
        ["medico"],
        active=False,
        extra_fields=extra_fields,
    )


def find_user_by_email(email: str) -> dict[str, Any] | None:
    bootstrap_users_if_needed()
    return _medicos().obter_por_email(normalize_email(email))


def find_user_by_id(user_id: str) -> dict[str, Any] | None:
    bootstrap_users_if_needed()
    return _medicos().obter(user_id)


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": user.get("name"),
    }


def sanitize_doctor_request(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "profiles": normalize_profiles(user.get("profiles")),
        "active": bool(user.get("active", True)),
        "crm": user.get("crm"),
        "specialty": user.get("specialty"),
        "approval_status": get_doctor_approval_status(user),
        "created_at": user.get("created_at"),
        "approved_at": user.get("approved_at"),
        "approved_by": user.get("approved_by"),
        "rejected_at": user.get("rejected_at"),
        "rejected_by": user.get("rejected_by"),
        "rejection_reason": user.get("rejection_reason"),
    }


def get_profile_details(profile: str) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    permissions = sorted(PROFILE_PERMISSIONS.get(normalized, set()))
    return {
        "name": normalized,
        "permissions": permissions,
        "redirect_to": PROFILE_REDIRECTS.get(normalized, "/app"),
    }


def authenticate_user(email: Any, password: Any, *, require_active: bool = True) -> dict[str, Any] | None:
    normalized_email = normalize_email(email)
    if not is_valid_email(normalized_email):
        return None
    if not isinstance(password, str) or not password:
        return None

    user = find_user_by_email(normalized_email)
    if not user:
        return None
    if not check_password_hash(user.get("password_hash", ""), password):
        return None
    if require_active and not user.get("active", True):
        return None
    return user


def get_doctor_approval_status(user: dict[str, Any]) -> str:
    status = user.get("approval_status")
    if status in {"pending", "approved", "rejected"}:
        return status
    return "approved" if user.get("active", True) else "pending"


def validate_user_profile_access(user: dict[str, Any], profile: str) -> None:
    normalized_profile = normalize_profile(profile)
    if not normalized_profile:
        raise AuthError("Perfil e obrigatorio.", 400)
    if normalized_profile not in normalize_profiles(user.get("profiles")):
        raise AuthError("Perfil nao permitido para este usuario.", 403)

    if normalized_profile == "medico":
        approval_status = get_doctor_approval_status(user)
        if approval_status == "pending":
            raise AuthError("Cadastro aguardando aprovação do administrador.", 403)
        if approval_status == "rejected":
            raise AuthError("Cadastro rejeitado. Entre em contato com a administração.", 403)
        if approval_status != "approved" or not user.get("active", True):
            raise AuthError("Cadastro aguardando aprovação do administrador.", 403)
        return

    if not user.get("active", True):
        raise AuthError("Conta inativa.", 403)


def list_doctor_requests(status: str = "pending") -> list[dict[str, Any]]:
    normalized_status = status if status in {"pending", "approved", "rejected", "all"} else "pending"
    bootstrap_users_if_needed()
    doctors = []
    for user in _medicos().listar():
        if "medico" not in normalize_profiles(user.get("profiles")):
            continue
        approval_status = get_doctor_approval_status(user)
        if normalized_status != "all" and approval_status != normalized_status:
            continue
        doctors.append(sanitize_doctor_request(user))

    status_order = {"pending": 0, "approved": 1, "rejected": 2}
    return sorted(
        doctors,
        key=lambda item: (
            status_order.get(item.get("approval_status"), 9),
            item.get("created_at") or "",
        ),
        reverse=False,
    )


def _update_doctor_request(user_id: str, updater) -> dict[str, Any]:
    user = find_user_by_id(user_id)
    if user is None:
        raise AuthError("Solicitacao de medico nao encontrada.", 404)
    if "medico" not in normalize_profiles(user.get("profiles")):
        raise AuthError("Usuario nao e medico.", 400)
    updater(user)
    return sanitize_doctor_request(_medicos().atualizar(user))


def approve_doctor_request(user_id: str, admin_id: str) -> dict[str, Any]:
    now = _utcnow().isoformat()

    def updater(user: dict[str, Any]) -> None:
        user["active"] = True
        user["approval_status"] = "approved"
        user["approved_at"] = now
        user["approved_by"] = admin_id
        user["rejected_at"] = None
        user["rejected_by"] = None
        user["rejection_reason"] = None

    return _update_doctor_request(user_id, updater)


def reject_doctor_request(user_id: str, admin_id: str, reason: Any = None) -> dict[str, Any]:
    now = _utcnow().isoformat()
    rejection_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None

    def updater(user: dict[str, Any]) -> None:
        user["active"] = False
        user["approval_status"] = "rejected"
        user["rejected_at"] = now
        user["rejected_by"] = admin_id
        user["rejection_reason"] = rejection_reason
        user["approved_at"] = None
        user["approved_by"] = None

    return _update_doctor_request(user_id, updater)


def create_access_token(user: dict[str, Any], profile: str) -> tuple[str, int]:
    normalized_profile = normalize_profile(profile)
    validate_user_profile_access(user, normalized_profile)

    expires_in = int(settings.auth_token_expiration_minutes) * 60
    now = _utcnow()
    payload = {
        "sub": user.get("id"),
        "email": user.get("email"),
        "profile": normalized_profile,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }

    secret = get_auth_secret()
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    return token, expires_in


def create_refresh_token(user: dict[str, Any], profile: str) -> tuple[str, int]:
    """Gera o refresh token (B22): vida mais longa, usado so para pedir um
    novo access token em /api/auth/refresh - nunca aceito nas rotas protegidas.
    """
    normalized_profile = normalize_profile(profile)
    expires_in = int(settings.auth_refresh_token_expiration_days) * 24 * 60 * 60
    now = _utcnow()
    payload = {
        "sub": user.get("id"),
        "profile": normalized_profile,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }

    secret = get_auth_secret()
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica e valida a assinatura/expiracao de qualquer token nosso
    (access ou refresh). Quem chama decide se o "type" do payload e o
    esperado - veja get_user_from_token e exchange_refresh_token.
    """
    if not token:
        raise AuthError("Token obrigatorio", 401)

    secret = get_auth_secret()
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("Token invalido", 401) from exc


def get_user_from_token(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = decode_access_token(token)
    if payload.get("type", "access") != "access":
        # Um refresh token nao pode ser usado para acessar rotas protegidas.
        raise AuthError("Token invalido", 401)

    user = find_user_by_id(payload.get("sub"))
    profile = normalize_profile(payload.get("profile"))

    if not user or not user.get("active", True):
        raise AuthError("Token invalido", 401)
    if profile not in normalize_profiles(user.get("profiles")):
        raise AuthError("Perfil nao permitido para este usuario", 403)

    return user, payload


def exchange_refresh_token(refresh_token: str) -> tuple[str, int, dict[str, Any]]:
    """Troca um refresh token valido por um novo access token (rota
    /api/auth/refresh). Nao exige o usuario estar com token de acesso -
    o proprio refresh token e a credencial.
    """
    payload = decode_access_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthError("Este endpoint espera um refresh token.", 401)

    user = find_user_by_id(payload.get("sub"))
    if not user or not user.get("active", True):
        raise AuthError("Token invalido", 401)

    profile = normalize_profile(payload.get("profile"))
    token, expires_in = create_access_token(user, profile)
    return token, expires_in, user


def user_has_profile(user: dict[str, Any], profile: str) -> bool:
    return normalize_profile(profile) in normalize_profiles(user.get("profiles"))


def profile_has_permission(profile: str, permission: str) -> bool:
    return permission in PROFILE_PERMISSIONS.get(normalize_profile(profile), set())
