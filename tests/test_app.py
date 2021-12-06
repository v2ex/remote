import pytest

from app import app


@pytest.fixture()
def client():
    with app.test_client() as client:
        yield client


def test_hello(client):
    response = client.get("/hello")
    assert b"region" in response.data


def test_ping(client):
    response = client.get("/ping")
    assert b"pong" in response.data


def test_dns_resolve(client):
    response = client.get("/dns/resolve?domain=example.com")
    assert response.status_code == 200
