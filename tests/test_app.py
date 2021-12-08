import base64
import importlib.util
import io
import json
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
    assert b"region" in response.data


def test_ping(client):
    response = client.get("/ping")
    assert b"pong" in response.data


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
        assert b"output" in response.data

        o = json.loads(response.data)

        uploaded_size = o["uploaded"]["size"]
        assert uploaded_size == len(open("tests/hello.jpeg", "rb").read())

        img = Image.open(io.BytesIO(base64.b64decode(o["output"])))
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
        assert b"output" in response.data

        o = json.loads(response.data)

        im = Image.open(io.BytesIO(base64.b64decode(o["output"])))
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

        o = json.loads(response.data)

        for size in AvatarSize:
            assert f"avatar{size}".encode("utf-8") in response.data
            im = Image.open(io.BytesIO(base64.b64decode(o[f"avatar{size}"]["body"])))
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

        o = json.loads(response.data)

        for size in AvatarSize:
            assert f"avatar{size}".encode("utf-8") in response.data
            im = Image.open(io.BytesIO(base64.b64decode(o[f"avatar{size}"]["body"])))
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

        o = json.loads(response.data)

        assert b"avatar24" in response.data
        im = Image.open(io.BytesIO(base64.b64decode(o["avatar24"]["body"])))
        assert im.size == (24, 24)

        assert b"avatar48" in response.data
        im = Image.open(io.BytesIO(base64.b64decode(o["avatar48"]["body"])))
        assert im.size == (48, 48)

        assert b"avatar73" in response.data
        im = Image.open(io.BytesIO(base64.b64decode(o["avatar73"]["body"])))
        assert im.size == (73, 73)

        assert b"avatar128" not in response.data
        assert b"avatar256" not in response.data
        assert b"avatar512" not in response.data


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
        assert b"image/png" in response.data
