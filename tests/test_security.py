"""Bounded offline security/compatibility regressions; no production database."""
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from pymysql._auth import sha2_rsa_encrypt
import main


def test_allowed_host_and_status_schema(monkeypatch):
    monkeypatch.setattr(main, "refresh_cache", lambda: None)
    with TestClient(main.app) as client:
        response = client.get("/status", headers={"host": "api.fossic.org"})
        assert response.status_code == 200
        assert set(response.json()) == {"status", "docs_url", "cache"}
        assert response.headers["content-type"] == "application/json"


def test_untrusted_and_malformed_hosts_are_rejected(monkeypatch):
    monkeypatch.setattr(main, "refresh_cache", lambda: None)
    with TestClient(main.app) as client:
        for host in ["attacker.invalid", "api.fossic.org/other?x=1", "api.fossic.org#fragment"]:
            assert client.get("/status", headers={"host": host}).status_code == 400


def test_public_get_cors_without_cookie_credentials(monkeypatch):
    monkeypatch.setattr(main, "refresh_cache", lambda: None)
    with TestClient(main.app) as client:
        response = client.get("/status", headers={"Origin": "https://index.fossic.org"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in response.headers
        response = client.options("/mods", headers={"Origin": "https://index.fossic.org",
            "Access-Control-Request-Method": "GET"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-methods"] == "GET"
        assert client.options("/mods", headers={"Origin": "https://index.fossic.org",
            "Access-Control-Request-Method": "POST"}).status_code == 400


def test_mysql_rsa_auth_primitive_survives_crypto_upgrade():
    # PyMySQL's caching_sha2_password helper uses RSA OAEP with SHA1.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
    password = b"offline-placeholder"
    salt = b"01234567890123456789"
    public_key = key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    encrypted = sha2_rsa_encrypt(password, salt, public_key)
    scrambled = key.decrypt(encrypted, oaep)
    clear = bytes(value ^ salt[index % len(salt)] for index, value in enumerate(scrambled))
    assert clear == password + b"\0"
