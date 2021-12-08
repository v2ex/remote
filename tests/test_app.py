import base64
import importlib.util
import io
import sys

import pytest
from PIL import Image

# mock config.py base on config.example.py
module_name = "config"
spec = importlib.util.spec_from_file_location(module_name, "config.example.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.modules[module_name] = module

from app import AvatarSize, app  # noqa


@pytest.fixture()
def client():
    with app.test_client() as client:
        yield client


def test_hello(client):
    response = client.get("/hello")
    assert "region" in response.json


def test_ping(client):
    response = client.get("/ping")
    assert response.json.get("message") == "pong"
    assert response.json.get("status") == "ok"
    assert response.json.get("success") is True


def test_dns_resolve(client):
    response = client.get("/dns/resolve?domain=example.com")
    assert response.status_code == 200


def test_images_prepare_jpeg(client):
    data = {}
    with open("tests/hello.jpeg", "rb") as image_file:
        data["file"] = (image_file, "hello.jpeg")
        response = client.post(
            "/images/prepare_jpeg",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        assert "output" in resp
        uploaded_size = resp["uploaded"]["size"]
        assert uploaded_size == len(open("tests/hello.jpeg", "rb").read())

        img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        assert img.getexif() == {}


def test_images_fit_320(client):
    data = {}
    with open("tests/hello.png", "rb") as image_file:
        data["file"] = (image_file, "hello.png")
        response = client.post(
            "/images/fit/320",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        assert "output" in resp
        im = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        assert im.size == (320, 320)


def test_images_resize_avatar(client):
    data = {}
    with open("tests/hello.png", "rb") as image_file:
        data["file"] = (image_file, "hello.png")
        response = client.post(
            "/images/resize_avatar",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        for size in AvatarSize:
            assert f"avatar{size}" in resp
            im = Image.open(io.BytesIO(base64.b64decode(resp[f"avatar{size}"]["body"])))
            assert im.size == (size, size)


def test_images_resize_avatar_svg(client):
    data = {}
    with open("tests/python.svg", "rb") as image_file:
        data["file"] = (image_file, "python.svg")
        response = client.post(
            "/images/resize_avatar",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        for size in AvatarSize:
            assert f"avatar{size}" in resp
            im = Image.open(io.BytesIO(base64.b64decode(resp[f"avatar{size}"]["body"])))
            assert im.size == (size, size)


def test_images_resize_avatar_1px(client):
    data = {}
    with open("tests/1px.png", "rb") as image_file:
        data["file"] = (image_file, "1px.png")
        response = client.post(
            "/images/resize_avatar",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        assert "avatar24" in resp
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar24"]["body"])))
        assert im.size == (24, 24)

        assert "avatar48" in resp
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar48"]["body"])))
        assert im.size == (48, 48)

        assert "avatar73" in resp
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar73"]["body"])))
        assert im.size == (73, 73)

        assert "avatar128" not in resp
        assert "avatar256" not in resp
        assert "avatar512" not in resp


def test_images_info_api_doc(client):
    response = client.get("/images/info")
    assert "usage" in response.json


def test_images_info(client):
    data = {}
    with open("tests/hello.png", "rb") as image_file:
        data["file"] = (image_file, "hello.png")
        response = client.post(
            "/images/info",
            data=data,
            follow_redirects=True,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

        resp = response.json

        assert resp.get("mime_type") == "image/png"
