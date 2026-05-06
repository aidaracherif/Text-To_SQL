"""
Tests unitaires pour auth/security.py

Couvre :
  - hash_password() : bcrypt, sel aléatoire, refus du mot de passe vide
  - verify_password() : retourne True/False sans crasher sur des hash mal formés
  - create_access_token() : claims valides + expiration
  - decode_access_token() : valide les bons tokens, rejette les mauvais
"""

from datetime import timedelta

import pytest
import jwt as pyjwt

from auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


# =============================================================================
# hash_password()
# =============================================================================

class TestHashPassword:

    def test_returns_string(self):
        result = hash_password("monpasswordsecret")
        assert isinstance(result, str)

    def test_hash_differs_from_password(self):
        """Le hash ne doit JAMAIS contenir le mot de passe en clair."""
        pwd = "supersecret123"
        hashed = hash_password(pwd)
        assert pwd not in hashed

    def test_each_call_produces_different_hash(self):
        """Le sel est aléatoire → 2 hash du même mot de passe diffèrent."""
        h1 = hash_password("mypassword")
        h2 = hash_password("mypassword")
        assert h1 != h2

    def test_rejects_empty_password(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_handles_unicode(self):
        """Mots de passe avec accents et emojis."""
        result = hash_password("pässwörd_émoji_🔐")
        assert isinstance(result, str)

    def test_hash_starts_with_bcrypt_marker(self):
        """Les hash bcrypt commencent par $2b$ (ou $2a$, $2y$)."""
        h = hash_password("test")
        assert h.startswith("$2")


# =============================================================================
# verify_password()
# =============================================================================

class TestVerifyPassword:

    def test_accepts_correct_password(self):
        pwd = "secret123"
        h = hash_password(pwd)
        assert verify_password(pwd, h) is True

    def test_rejects_wrong_password(self):
        h = hash_password("secret123")
        assert verify_password("WRONG", h) is False

    def test_rejects_empty_password(self):
        h = hash_password("secret")
        assert verify_password("", h) is False

    def test_rejects_empty_hash(self):
        assert verify_password("secret", "") is False

    def test_does_not_crash_on_malformed_hash(self):
        """Si le hash en BDD est corrompu, on retourne False (pas d'exception)."""
        assert verify_password("secret", "this-is-not-a-bcrypt-hash") is False

    def test_does_not_crash_on_none_values(self):
        """Cas extrême : None (ne devrait pas arriver, mais on blinde)."""
        assert verify_password(None, "") is False
        assert verify_password("", None) is False


# =============================================================================
# create_access_token() + decode_access_token()
# =============================================================================

class TestJwtTokens:

    def test_creates_decodable_token(self):
        """Token créé → on doit pouvoir le décoder et retrouver les claims."""
        token = create_access_token(user_id=42, username="alice", role="user")
        payload = decode_access_token(token)
        assert payload["sub"] == "alice"
        assert payload["user_id"] == 42
        assert payload["role"] == "user"

    def test_token_includes_expiration(self):
        token = create_access_token(user_id=1, username="bob", role="admin")
        payload = decode_access_token(token)
        # exp et iat présents
        assert "exp" in payload
        assert "iat" in payload
        # exp > iat
        assert payload["exp"] > payload["iat"]

    def test_expired_token_rejected(self):
        """Un token expiré doit lever ExpiredSignatureError."""
        token = create_access_token(
            user_id=1,
            username="alice",
            role="user",
            expires_delta=timedelta(seconds=-1),  # déjà expiré
        )
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_tampered_token_rejected(self):
        """Si on modifie le token, la signature ne match plus."""
        token = create_access_token(user_id=1, username="alice", role="user")
        # Modifier un caractère au milieu de la signature
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_garbage_token_rejected(self):
        """Token complètement invalide → InvalidTokenError."""
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token("not-a-jwt-at-all")

    def test_admin_role_preserved(self):
        token = create_access_token(user_id=1, username="admin", role="admin")
        payload = decode_access_token(token)
        assert payload["role"] == "admin"

    def test_user_role_preserved(self):
        token = create_access_token(user_id=1, username="bob", role="user")
        payload = decode_access_token(token)
        assert payload["role"] == "user"


# =============================================================================
# CYCLE COMPLET — hash → verify → token → decode
# =============================================================================

class TestFullAuthCycle:

    def test_register_then_login_flow(self):
        """
        Simule le parcours complet :
        1. Register : hash_password
        2. Login    : verify_password puis create_access_token
        3. Request  : decode_access_token
        """
        # 1. Register
        password_clear = "MyS3cr3t!"
        password_hash = hash_password(password_clear)
        assert password_hash != password_clear

        # 2. Login : vérification du mot de passe + création token
        assert verify_password(password_clear, password_hash) is True
        token = create_access_token(user_id=1, username="alice", role="user")

        # 3. Request : décodage du token
        payload = decode_access_token(token)
        assert payload["sub"] == "alice"