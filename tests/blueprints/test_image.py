import base64
import io
from unittest.mock import patch

from PIL import Image

from remote.blueprints.image import AvatarSize
from tests.test_app import TestBase


class TestImage(TestBase):
    @property
    def hello_jpeg(self):
        return self.get_fixture_path("hello.jpeg")

    @property
    def hello_png(self):
        return self.get_fixture_path("hello.png")

    @property
    def python_svg(self):
        return self.get_fixture_path("python.svg")

    @property
    def px1_png(self):
        return self.get_fixture_path("1px.png")

    @property
    def px200_jpg(self):
        return self.get_fixture_path("200px.jpg")

    def test_images_info(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/png")

    def test_images_info_error_1(self):
        response = self.client.post("/images/info")
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("No file", resp["message"])

    def test_images_info_error_2(self):
        svg2png_func = "remote.blueprints.image.cairosvg.svg2png"

        with patch(svg2png_func, side_effect=Exception("Mock Exception")):
            with open(self.python_svg, "rb") as image_file:
                data = {"file": (image_file, "python.svg")}
                response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("Unable to determine", resp["message"])

    def test_images_info_api_doc(self):
        response = self.client.get("/images/info")
        self.assertEqual(response.status_code, 200)
        self.assertIn("usage", response.json)

    def test_prepare_jpeg(self):
        with open(self.hello_jpeg, "rb") as image_file:
            data = {"file": (image_file, "hello.jpeg")}
            response = self.client.post("/images/prepare_jpeg", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        real_size = len(open(self.hello_jpeg, "rb").read())
        self.assertEqual(resp["uploaded"]["size"], real_size)

        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.getexif(), {})

    def test_prepare_jpeg_api_doc(self):
        response = self.client.get("/images/prepare_jpeg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("usage", response.json)

    def test_fit_320(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/fit/320", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        putput_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(putput_img.size, (320, 320))

    def test_fit_error_1(self):
        response = self.client.post("/images/fit/320")
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("No file", resp["message"])

    def test_fit_error_2(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/fit/0", data=data)
        self.assertEqual(response.status_code, 500)

        resp = response.json

        self.assertIn("Error occurred", resp["message"])

    def test_resize_avatar(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        for size in AvatarSize:
            self.assertIn(f"avatar{size}", resp)
            _body = resp[f"avatar{size}"]["body"]
            output_img = Image.open(io.BytesIO(base64.b64decode(_body)))
            self.assertEqual(output_img.size, (size, size))

    def test_resize_avatar_svg(self):
        with open(self.python_svg, "rb") as image_file:
            data = {"file": (image_file, "python.svg")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        for size in AvatarSize:
            self.assertIn(f"avatar{size}", resp)
            _body = resp[f"avatar{size}"]["body"]
            output_img = Image.open(io.BytesIO(base64.b64decode(_body)))
            self.assertEqual(output_img.size, (size, size))

    def test_resize_avatar_1px(self):
        with open(self.px1_png, "rb") as image_file:
            data = {"file": (image_file, "1px.png")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("avatar24", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar24"]["body"])))
        self.assertEqual(im.size, (24, 24))

        self.assertIn("avatar48", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar48"]["body"])))
        self.assertEqual(im.size, (48, 48))

        self.assertIn("avatar73", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar73"]["body"])))
        self.assertEqual(im.size, (73, 73))

        self.assertNotIn("avatar128", resp)
        self.assertNotIn("avatar256", resp)
        self.assertNotIn("avatar512", resp)

    def test_resize_avatar_200px(self):
        with open(self.px200_jpg, "rb") as image_file:
            data = {"file": (image_file, "200px.jpg")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("avatar24", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar24"]["body"])))
        self.assertEqual(im.size, (24, 24))

        self.assertIn("avatar48", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar48"]["body"])))
        self.assertEqual(im.size, (48, 48))

        self.assertIn("avatar73", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar73"]["body"])))
        self.assertEqual(im.size, (73, 73))

        self.assertIn("avatar128", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar128"]["body"])))
        self.assertEqual(im.size, (128, 128))

        self.assertNotIn("avatar256", resp)
        self.assertNotIn("avatar512", resp)
