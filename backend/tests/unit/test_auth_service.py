import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.service import AuthError, AuthService


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def make_token(private_key, **claims) -> str:
    payload = {"sub": "user-123", "email": "owner@amazona.local", **claims}
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_verify_accepts_a_correctly_signed_token(key_pair):
    private_key, public_key = key_pair
    service = AuthService(get_signing_key=lambda token: public_key)

    user = service.verify(make_token(private_key))

    assert user.sub == "user-123"
    assert user.email == "owner@amazona.local"


def test_verify_rejects_a_token_signed_with_a_different_key(key_pair):
    _, public_key = key_pair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    service = AuthService(get_signing_key=lambda token: public_key)

    with pytest.raises(AuthError):
        service.verify(make_token(other_private_key))


def test_verify_rejects_a_malformed_token(key_pair):
    _, public_key = key_pair
    service = AuthService(get_signing_key=lambda token: public_key)

    with pytest.raises(AuthError):
        service.verify("not-a-jwt-at-all")


def test_verify_rejects_a_token_missing_the_sub_claim(key_pair):
    private_key, public_key = key_pair
    service = AuthService(get_signing_key=lambda token: public_key)
    token = jwt.encode({"email": "owner@amazona.local"}, private_key, algorithm="RS256")

    with pytest.raises(AuthError):
        service.verify(token)
