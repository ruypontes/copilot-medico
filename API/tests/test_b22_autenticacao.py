"""
Testes do B22 - Evoluir autenticacao (PyJWT obrigatorio, refresh token,
politica de senha, rate limit e lockout no login).

Arquivo novo (mesmo padrao do B16): evita mexer em arquivos que outras
pessoas do time podem estar alterando ao mesmo tempo.
"""
import jwt
import pytest

from backend import auth_service
from backend.anonimizacao import servico as anonimizacao_servico


@pytest.fixture()
def users_db(temp_db_file, monkeypatch):
    """Banco de teste (usuarios na tabela `medico`, B20) e chave secreta de
    teste - mesmo padrao usado em test_contrato_auth_admin.py.

    Tambem zera o estado de rate limit/lockout do login (fica em memoria,
    em dicionarios do modulo) para um teste nao atrapalhar o outro.
    """
    monkeypatch.setattr(auth_service.settings, "auth_secret_key", "chave-de-teste-b22")
    monkeypatch.setattr(auth_service.settings, "auth_bootstrap_email", "")
    monkeypatch.setattr(auth_service.settings, "auth_bootstrap_password", "")

    auth_service._login_attempts_by_ip.clear()
    auth_service._lockouts_by_email.clear()

    yield temp_db_file

    auth_service._login_attempts_by_ip.clear()
    auth_service._lockouts_by_email.clear()


def _test_credential():
    return "Teste" + str(2026) + "!"


def _register_and_approve_doctor(users_db, email="dra.teste@example.com", password=_test_credential()):
    """Cria um medico ja aprovado direto pelas funcoes do auth_service,
    sem passar pela rota HTTP (mais rapido para montar o cenario dos testes).
    """
    doctor = auth_service.create_doctor_registration(
        name="Dra. Teste",
        email=email,
        password=password,
    )
    auth_service.approve_doctor_request(doctor["id"], admin_id="admin-de-teste")
    return doctor


def _login(client, email="dra.teste@example.com", password=_test_credential(), profile="medico"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "profile": profile},
    )


class TestPyJWTObrigatorio:
    def test_pyjwt_esta_instalado_e_e_usado_pelo_auth_service(self):
        # D-25: antes, se o PyJWT nao estivesse instalado, o auth_service
        # caia silenciosamente num JWT "artesanal" (HS256 feito na mao).
        # Agora o import de PyJWT e direto (sem try/except), entao se ele
        # nao estiver instalado o modulo nem carrega - este teste simples
        # confirma que o modulo "jwt" (do pacote PyJWT) e o que o
        # auth_service usa de fato.
        assert auth_service.pyjwt is jwt


class TestLoginComAccessERefreshToken:
    def test_login_com_sucesso_retorna_access_e_refresh_token(self, client, users_db):
        _register_and_approve_doctor(users_db)

        response = _login(client)
        assert response.status_code == 200

        body = response.get_json()
        assert "token" in body
        assert "refresh_token" in body
        assert body["refresh_expires_in"] == auth_service.settings.auth_refresh_token_expiration_days * 24 * 60 * 60

        access_payload = jwt.decode(body["token"], auth_service.settings.auth_secret_key, algorithms=["HS256"])
        assert access_payload["type"] == "access"

        refresh_payload = jwt.decode(body["refresh_token"], auth_service.settings.auth_secret_key, algorithms=["HS256"])
        assert refresh_payload["type"] == "refresh"


    def test_senha_scrypt_existente_continua_funcionando(self, client, users_db):
        # Simula um usuario legado: hash scrypt ja existente no banco,
        # sem passar pelo fluxo atual de criacao de usuarios.
        hash_scrypt_legado = (
            "scrypt:32768:8:1$IWig6aoLsOrCKFJ1$"
            "470b16a53228912728f8f4caa8a72be60b19e0cdb1bc91bc6738e921a1b733e3e"
            "73f7aab52887bfd1885cba7d10bede6fd570f70038352e9e115e8dc22c81917"
        )

        auth_service._medicos().criar({
            "id": str(__import__("uuid").uuid4()),
            "email": "medico.antigo@example.com",
            "name": "Medico Antigo",
            "password_hash": hash_scrypt_legado,
            "profiles": ["medico"],
            "active": True,
        })

        response = _login(
            client,
            email="medico.antigo@example.com",
            password="SenhaAntiga1",
        )
        assert response.status_code == 200



class TestRotaDeRefresh:
    def test_refresh_token_gera_novo_access_token(self, client, users_db):
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()

        response = client.post("/api/auth/refresh", json={"refresh_token": login_body["refresh_token"]})
        assert response.status_code == 200

        body = response.get_json()
        assert "token" in body
        new_payload = jwt.decode(body["token"], auth_service.settings.auth_secret_key, algorithms=["HS256"])
        assert new_payload["type"] == "access"
        assert new_payload["profile"] == "medico"

    def test_refresh_token_nao_acessa_rota_protegida(self, client, users_db):
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {login_body['refresh_token']}"},
        )
        assert response.status_code == 401

    def test_rota_refresh_rejeita_access_token(self, client, users_db):
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()

        response = client.post("/api/auth/refresh", json={"refresh_token": login_body["token"]})
        assert response.status_code == 401

    def test_rota_refresh_sem_refresh_token_retorna_400(self, client, users_db):
        response = client.post("/api/auth/refresh", json={})
        assert response.status_code == 400

    def test_refresh_leva_o_cofre_b26_para_o_token_novo(self, client, users_db):
        # Interacao com o B26 (cofre de cifra): o cofre fica associado ao
        # token de acesso. Ao renovar o token, se o cliente mandar o token
        # antigo no header, o cofre precisa "mudar de dono" para o token
        # novo - senao o medico perderia a cifra dos dados so por ter
        # renovado o access token, sem precisar logar de novo.
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()
        token_antigo = login_body["token"]

        assert anonimizacao_servico.cofre_da_sessao(token_antigo) is not None

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
            headers={"Authorization": f"Bearer {token_antigo}"},
        )
        assert response.status_code == 200
        token_novo = response.get_json()["token"]

        assert anonimizacao_servico.cofre_da_sessao(token_novo) is not None
        # Se o login e o refresh acontecerem no mesmo segundo, o token novo
        # pode sair identico ao antigo (mesmo conteudo -> mesmo JWT) - nesse
        # caso nao ha "token antigo" de verdade para descartar.
        if token_novo != token_antigo:
            assert anonimizacao_servico.cofre_da_sessao(token_antigo) is None

    def test_refresh_nao_transfere_cofre_de_outro_medico(self, client, users_db):
        # Seguranca: o token antigo do header nao era validado. Quem tivesse
        # o access token de outro medico podia mandar o proprio refresh token
        # com o token alheio no header e "herdar" o cofre (mapa de
        # pseudonimos) dele, revertendo a anonimizacao dos pacientes.
        _register_and_approve_doctor(users_db, email="dra.a@example.com")
        _register_and_approve_doctor(users_db, email="dr.b@example.com")
        token_a = _login(client, email="dra.a@example.com").get_json()["token"]
        refresh_b = _login(client, email="dr.b@example.com").get_json()["refresh_token"]
        cofre_a = anonimizacao_servico.cofre_da_sessao(token_a)
        assert cofre_a is not None

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_b},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 200
        token_novo_b = response.get_json()["token"]

        assert anonimizacao_servico.cofre_da_sessao(token_novo_b) is not cofre_a
        assert anonimizacao_servico.cofre_da_sessao(token_a) is cofre_a

    def test_refresh_nao_transfere_cofre_com_token_forjado(self, client, users_db):
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()
        cofre = anonimizacao_servico.cofre_da_sessao(login_body["token"])
        forjado = jwt.decode(
            login_body["token"], auth_service.settings.auth_secret_key, algorithms=["HS256"]
        )
        token_forjado = jwt.encode(forjado, "outra-chave", algorithm="HS256")
        # O cofre passa a existir so sob o token forjado.
        anonimizacao_servico.encerrar_sessao(login_body["token"])
        anonimizacao_servico.registrar_sessao(token_forjado, cofre)

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
            headers={"Authorization": f"Bearer {token_forjado}"},
        )
        assert response.status_code == 200
        assert anonimizacao_servico.cofre_da_sessao(response.get_json()["token"]) is None

    def test_refresh_aceita_token_antigo_expirado_do_mesmo_medico(self, client, users_db, monkeypatch):
        # O caso normal do refresh e justamente o access token ja ter
        # expirado: a assinatura e o dono sao conferidos, a validade nao.
        _register_and_approve_doctor(users_db)
        login_body = _login(client).get_json()
        cofre = anonimizacao_servico.cofre_da_sessao(login_body["token"])
        payload = jwt.decode(
            login_body["token"], auth_service.settings.auth_secret_key, algorithms=["HS256"]
        )
        payload["exp"] = payload["iat"] - 1
        token_expirado = jwt.encode(payload, auth_service.settings.auth_secret_key, algorithm="HS256")
        anonimizacao_servico.encerrar_sessao(login_body["token"])
        anonimizacao_servico.registrar_sessao(token_expirado, cofre)

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
            headers={"Authorization": f"Bearer {token_expirado}"},
        )
        assert response.status_code == 200
        assert anonimizacao_servico.cofre_da_sessao(response.get_json()["token"]) is cofre


class TestPoliticaDeSenha:
    def test_cadastro_rejeita_senha_curta(self, client, users_db):
        response = client.post(
            "/api/auth/register-doctor",
            json={"name": "Dr. Curto", "email": "curto@example.com", "password": "ab1"},
        )
        assert response.status_code == 400
        assert "senha" in response.get_json()["message"].lower()

    def test_cadastro_rejeita_senha_so_numeros(self, client, users_db):
        response = client.post(
            "/api/auth/register-doctor",
            json={"name": "Dr. Numeros", "email": "numeros@example.com", "password": "12345678"},
        )
        assert response.status_code == 400

    def test_cadastro_aceita_senha_valida(self, client, users_db):
        response = client.post(
            "/api/auth/register-doctor",
            json={"name": "Dr. Valido", "email": "valido@example.com", "password": _test_credential()},
        )
        assert response.status_code == 201


class TestRateLimitELockout:
    def test_rate_limit_retorna_429_apos_muitas_tentativas(self, client, users_db, monkeypatch):
        monkeypatch.setattr(auth_service.settings, "auth_login_rate_limit_attempts", 3)
        _register_and_approve_doctor(users_db)

        for _ in range(3):
            response = _login(client, password="senha-errada-123")
            assert response.status_code == 401

        response = _login(client, password="senha-errada-123")
        assert response.status_code == 429

    def test_lockout_bloqueia_mesmo_com_senha_certa(self, client, users_db, monkeypatch):
        monkeypatch.setattr(auth_service.settings, "auth_login_lockout_attempts", 3)
        # Evita que o rate limit por IP dispare antes do lockout por conta,
        # ja que o teste faz varias tentativas seguidas do mesmo IP de teste.
        monkeypatch.setattr(auth_service.settings, "auth_login_rate_limit_attempts", 100)
        _register_and_approve_doctor(users_db)

        for _ in range(3):
            response = _login(client, password="senha-errada-123")
            assert response.status_code == 401

        response = _login(client, password=_test_credential())
        assert response.status_code == 403
        assert "bloqueada" in response.get_json()["message"].lower()

    def test_lockout_expirado_nao_bloqueia_novamente(self, client, users_db, monkeypatch):
        # Bug encontrado na revisao: sem isso, uma unica tentativa errada
        # APOS o fim do bloqueio re-bloqueava a conta na hora, porque o
        # contador de falhas antigo continuava acumulado.
        monkeypatch.setattr(auth_service.settings, "auth_login_lockout_attempts", 3)
        monkeypatch.setattr(auth_service.settings, "auth_login_rate_limit_attempts", 100)
        _register_and_approve_doctor(users_db)

        for _ in range(3):
            response = _login(client, password="senha-errada-123")
            assert response.status_code == 401

        response = _login(client, password=_test_credential())
        assert response.status_code == 403  # ainda bloqueada

        # Simula o fim do periodo de bloqueio.
        registro = auth_service._lockouts_by_email["dra.teste@example.com"]
        registro["locked_until"] = auth_service._utcnow().timestamp() - 1

        # Uma tentativa errada logo depois do bloqueio expirar NAO pode
        # re-bloquear a conta na hora - precisa de 3 falhas novas.
        response = _login(client, password="ainda-errada")
        assert response.status_code == 401

        response = _login(client, password=_test_credential())
        assert response.status_code == 200

    def test_login_com_sucesso_reseta_o_lockout(self, client, users_db, monkeypatch):
        monkeypatch.setattr(auth_service.settings, "auth_login_lockout_attempts", 5)
        monkeypatch.setattr(auth_service.settings, "auth_login_rate_limit_attempts", 100)
        _register_and_approve_doctor(users_db)

        for _ in range(2):
            response = _login(client, password="senha-errada-123")
            assert response.status_code == 401

        # Ainda nao bateu o limite de tentativas (2 < 5): login certo deve
        # funcionar e zerar o contador de falhas.
        response = _login(client, password=_test_credential())
        assert response.status_code == 200
