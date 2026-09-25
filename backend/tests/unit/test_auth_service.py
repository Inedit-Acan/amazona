import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.service import AuthError, AuthService

SUPABASE_URL = "https://example.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
AUDIENCE = "authenticated"


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def service(key_pair):
    _, public_key = key_pair
    return AuthService(supabase_url=SUPABASE_URL, audience=AUDIENCE, get_signing_key=lambda token: public_key)


def make_token(private_key, **claims) -> str:
    """A complete Supabase-shaped access token. Every claim here is one the
    service now requires, so a test that drops one is testing a rejection."""
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": "user-123",
        "email": "owner@amazona.local",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + datetime.timedelta(hours=1),
        "iat": now,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_verify_accepts_a_correctly_signed_token(service, key_pair):
    private_key, _ = key_pair

    user = service.verify(make_token(private_key))

    assert user.sub == "user-123"
    assert user.email == "owner@amazona.local"


def test_verify_rejects_a_token_signed_with_a_different_key(service):
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(AuthError):
        service.verify(make_token(other_private_key))


def test_verify_rejects_a_malformed_token(service):
    with pytest.raises(AuthError):
        service.verify("not-a-jwt-at-all")


def test_verify_rejects_a_token_missing_the_sub_claim(service, key_pair):
    private_key, public_key = key_pair
    now = datetime.datetime.now(datetime.UTC)
    token = jwt.encode(
        {"email": "owner@amazona.local", "iss": ISSUER, "aud": AUDIENCE, "exp": now + datetime.timedelta(hours=1)},
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthError):
        service.verify(token)


# --- Milestone 29: an incomplete token is no longer a valid one --------------


def test_verify_rejects_an_expired_token(service, key_pair):
    private_key, _ = key_pair
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)

    with pytest.raises(AuthError):
        service.verify(make_token(private_key, exp=past))


def test_verify_rejects_a_token_without_an_expiry(service, key_pair):
    private_key, public_key = key_pair
    token = jwt.encode(
        {"sub": "user-123", "iss": ISSUER, "aud": AUDIENCE}, private_key, algorithm="RS256"
    )

    with pytest.raises(AuthError):
        service.verify(token)


def test_verify_rejects_a_token_from_another_issuer(service, key_pair):
    private_key, _ = key_pair

    with pytest.raises(AuthError):
        service.verify(make_token(private_key, iss="https://attacker.example.com/auth/v1"))


def test_verify_rejects_a_token_for_another_audience(service, key_pair):
    private_key, _ = key_pair

    with pytest.raises(AuthError):
        service.verify(make_token(private_key, aud="some-other-service"))
