"""Cifra do mapa de pseudonimos com chave derivada da senha (B26 / ADR-03).

Modelo de envelope, em duas chaves:

    senha do medico --scrypt--> KEK  --AES-GCM--> [DEK cifrada no banco]
                                                      |
                                      DEK --AES-GCM--> dados do paciente

Por que nao cifrar direto com a chave da senha: trocar a senha obrigaria a
recifrar todas as linhas de `pseudonimo` e todos os mapas de consulta. Com o
envelope, a troca so reembrulha a DEK - uma operacao, nao N.

Consequencia operacional honesta: a DEK so existe em memoria enquanto houver
sessao aberta. Reiniciar o backend exige novo login para voltar a decifrar.
Isso e inerente a "chave derivada da senha" - o servidor nao pode guardar a
senha, e sem ela nao ha como reconstruir a KEK.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Parametros do scrypt. n=2**14 leva ~100 ms num notebook comum: caro o
# bastante para forca bruta, barato o bastante para rodar uma vez por login.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
TAMANHO_CHAVE = 32           # AES-256
TAMANHO_SALT = 16
TAMANHO_NONCE = 12           # recomendado para GCM

ALGORITMO = "aesgcm-v1"
ALGORITMO_SEM_CIFRA = "none"  # espelha models.ALGORITMO_SEM_CIFRA (B19)


class CriptografiaIndisponivel(RuntimeError):
    """`cryptography` nao instalado - o backend deve falhar alto, nao silenciar."""


class FalhaAoDecifrar(ValueError):
    """Chave errada ou dado corrompido/adulterado (GCM detecta os dois)."""


def _aesgcm(chave: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as erro:  # pragma: no cover - ambiente sem a lib
        raise CriptografiaIndisponivel(
            "pacote `cryptography` ausente; instale com `pip install -r requirements.txt`"
        ) from erro
    return AESGCM(chave)


def derivar_chave(senha: str, salt: bytes) -> bytes:
    """KEK a partir da senha do medico (scrypt, igual ao werkzeug usa)."""
    import hashlib

    if not senha:
        raise ValueError("senha vazia nao deriva chave")
    return hashlib.scrypt(
        senha.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=TAMANHO_CHAVE,
    )


def gerar_salt() -> bytes:
    return os.urandom(TAMANHO_SALT)


def cifrar(chave: bytes, dados: bytes, associados: bytes | None = None) -> bytes:
    """AES-GCM; o nonce aleatorio vai no inicio do blob."""
    nonce = os.urandom(TAMANHO_NONCE)
    return nonce + _aesgcm(chave).encrypt(nonce, dados, associados)


def decifrar(chave: bytes, blob: bytes, associados: bytes | None = None) -> bytes:
    if len(blob) <= TAMANHO_NONCE:
        raise FalhaAoDecifrar("blob menor que o nonce")
    nonce, corpo = blob[:TAMANHO_NONCE], blob[TAMANHO_NONCE:]
    try:
        return _aesgcm(chave).decrypt(nonce, corpo, associados)
    except CriptografiaIndisponivel:
        raise
    except Exception as erro:
        raise FalhaAoDecifrar("nao foi possivel decifrar (chave errada ou dado alterado)") from erro


# ---------------------------------------------------------------------------
# Envelope: DEK embrulhada pela KEK da senha
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cofre:
    """DEK aberta, viva apenas durante a sessao do medico."""

    dek: bytes

    def cifrar_json(self, dados: dict) -> bytes:
        bruto = json.dumps(dados, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return cifrar(self.dek, bruto)

    def decifrar_json(self, blob: bytes) -> dict:
        return json.loads(decifrar(self.dek, blob).decode("utf-8"))


def criar_cofre(senha: str) -> tuple[Cofre, bytes, bytes]:
    """Primeira vez: sorteia a DEK e a embrulha com a KEK da senha.

    Devolve (cofre, dek_cifrada, salt) - os dois ultimos vao para o banco.
    """
    salt = gerar_salt()
    dek = os.urandom(TAMANHO_CHAVE)
    dek_cifrada = cifrar(derivar_chave(senha, salt), dek)
    return Cofre(dek=dek), dek_cifrada, salt


def abrir_cofre(senha: str, dek_cifrada: bytes, salt: bytes) -> Cofre:
    """Login: reconstroi a KEK e desembrulha a DEK."""
    if not dek_cifrada or not salt:
        raise FalhaAoDecifrar("medico ainda nao tem chave de dados")
    return Cofre(dek=decifrar(derivar_chave(senha, salt), dek_cifrada))


def reembrulhar(cofre: Cofre, nova_senha: str) -> tuple[bytes, bytes]:
    """Troca de senha: so a DEK e reembrulhada; os dados ficam como estao."""
    salt = gerar_salt()
    return cifrar(derivar_chave(nova_senha, salt), cofre.dek), salt
