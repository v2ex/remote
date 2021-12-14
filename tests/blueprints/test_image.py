import base64
import io
from unittest.mock import patch

from PIL import Image

from remote.utilities.image import AvatarSize
from tests.fixture import TestFixture
from tests.test_app import TestBase


class TestImage(TestBase, TestFixture):
    def test_images_info_api_doc(self):
        response = self.client.get("/images/info")
        self.assertEqual(response.status_code, 200)
        self.assertIn("usage", response.json)

    def test_images_info_icns(self):
        with open(self.sunny_icns, "rb") as image_file:
            data = {"file": (image_file, "sunny.icns")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/x-icns")
        self.assertEqual(resp["binary_size"], len(open(self.sunny_icns, "rb").read()))
        self.assertEqual(resp["frames"], 1)

    def test_images_info_png(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/png")
        self.assertEqual(resp["binary_size"], len(open(self.hello_png, "rb").read()))
        self.assertEqual(resp["frames"], 1)

    def test_images_info_svg(self):
        with open(self.python_svg, "rb") as image_file:
            data = {"file": (image_file, "python.svg")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/svg+xml")
        self.assertEqual(resp["binary_size"], len(open(self.python_svg, "rb").read()))
        self.assertEqual(resp["frames"], 1)

    def test_images_info_webp(self):
        with open(self.test_webp, "rb") as image_file:
            data = {"file": (image_file, "test.webp")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/webp")
        self.assertEqual(resp["binary_size"], len(open(self.test_webp, "rb").read()))
        self.assertEqual(resp["frames"], Image.open(self.test_webp).n_frames)

    def test_images_info_gif(self):
        with open(self.animated_gif, "rb") as image_file:
            data = {"file": (image_file, "animated.gif")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/gif")
        self.assertEqual(resp["binary_size"], len(open(self.animated_gif, "rb").read()))
        self.assertEqual(resp["frames"], Image.open(self.animated_gif).n_frames)

    def test_images_info_avif(self):
        with open(self.cap_avif, "rb") as image_file:
            data = {"file": (image_file, "cap.avif")}
            response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn(resp["mime_type"], "image/avif")
        self.assertEqual(resp["binary_size"], len(open(self.cap_avif, "rb").read()))

    def test_images_info_error_1(self):
        response = self.client.post("/images/info")
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("No file", resp["message"])

    def test_images_info_error_2(self):
        svg2png_func = "remote.utilities.image.cairosvg.svg2png"

        with patch(svg2png_func, side_effect=Exception("Mock Exception")):
            with open(self.python_svg, "rb") as image_file:
                data = {"file": (image_file, "python.svg")}
                response = self.client.post("/images/info", data=data)
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("Unable to determine", resp["message"])

    def test_prepare_jpeg_api_doc(self):
        response = self.client.get("/images/prepare_jpeg")
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

    def test_prepare_jpeg_error_1(self):
        response = self.client.post("/images/prepare_jpeg")
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("No file", resp["message"])

    def test_prepare_jpeg_error_2(self):
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post("/images/prepare_jpeg", data=data)
        self.assertEqual(response.status_code, 400)

        resp = response.json

        self.assertIn("only for processing JPEG", resp["message"])

    def test_fit_api_doc(self):
        response = self.client.get("/images/fit/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("usage", response.json)

    def test_fit_1(self):
        target_size = 1
        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post(f"/images/fit/{target_size}", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.size, (target_size, target_size))

    def test_fit_320(self):
        target_size = 320
        original_size = Image.open(self.hello_png).size
        lw_aspect = original_size[0] / original_size[1]
        if lw_aspect > 1:
            _target_size = (target_size, int(target_size / lw_aspect))
        else:
            _target_size = (int(target_size * lw_aspect), target_size)

        with open(self.hello_png, "rb") as image_file:
            data = {"file": (image_file, "hello.png")}
            response = self.client.post(f"/images/fit/{target_size}", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.size, _target_size)

    def test_fit_avif_320(self):
        target_size = 320
        original_size = Image.open(self.cap_avif).size
        lw_aspect = original_size[0] / original_size[1]
        if lw_aspect > 1:
            _target_size = (target_size, int(target_size / lw_aspect))
        else:
            _target_size = (int(target_size * lw_aspect), target_size)

        with open(self.cap_avif, "rb") as image_file:
            data = {"file": (image_file, "cap.avif")}
            response = self.client.post(f"/images/fit/{target_size}", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.size, _target_size)

    def test_fit_icns_36(self):
        target_size = 36
        original_size = Image.open(self.sunny_icns).size
        lw_aspect = original_size[0] / original_size[1]
        if lw_aspect > 1:
            _target_size = (target_size, int(target_size / lw_aspect))
        else:
            _target_size = (int(target_size * lw_aspect), target_size)

        with open(self.sunny_icns, "rb") as image_file:
            data = {"file": (image_file, "sunny.icns")}
            response = self.client.post(f"/images/fit/{target_size}", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.size, _target_size)

    def test_fit_oversize(self):
        original_size = Image.open(self.hello_jpeg).size
        target_size = max(original_size) + 100
        with open(self.hello_jpeg, "rb") as image_file:
            data = {"file": (image_file, "hello.jpeg")}
            response = self.client.post(f"/images/fit/{target_size}", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("output", resp)
        output_img = Image.open(io.BytesIO(base64.b64decode(resp["output"])))
        self.assertEqual(output_img.size, original_size)

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

    def test_resize_avatar_api_doc(self):
        response = self.client.get("/images/resize_avatar")
        self.assertEqual(response.status_code, 200)
        self.assertIn("usage", response.json)

    def test_resize_avatar_icns(self):
        with open(self.sunny_icns, "rb") as image_file:
            data = {"file": (image_file, "sunny.icns")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        for size in AvatarSize:
            if size.is_mandatory:
                self.assertIn(f"avatar{size}", resp)
                _body = resp[f"avatar{size}"]["body"]
                output_img = Image.open(io.BytesIO(base64.b64decode(_body)))
                self.assertEqual(output_img.size, (size, size))
                self.assertEqual(output_img.format, "PNG")

    def test_resize_avatar_png(self):
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
            self.assertEqual(output_img.format, "PNG")

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
            self.assertEqual(output_img.format, "PNG")

    def test_resize_avatar_avif(self):
        with open(self.cap_avif, "rb") as image_file:
            data = {"file": (image_file, "cap.avif")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        for size in AvatarSize:
            self.assertIn(f"avatar{size}", resp)
            _body = resp[f"avatar{size}"]["body"]
            output_img = Image.open(io.BytesIO(base64.b64decode(_body)))
            self.assertEqual(output_img.size, (size, size))
            self.assertEqual(output_img.format, "PNG")

    def test_resize_avatar_gif(self):
        with open(self.animated_gif, "rb") as image_file:
            data = {"file": (image_file, "animated.gif")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        for size in AvatarSize:
            self.assertIn(f"avatar{size}", resp)
            _body = resp[f"avatar{size}"]["body"]
            output_img = Image.open(io.BytesIO(base64.b64decode(_body)))
            self.assertEqual(output_img.size, (size, size))
            self.assertEqual(output_img.format, "PNG")

    def test_resize_avatar_1px(self):
        with open(self.px1_png, "rb") as image_file:
            data = {"file": (image_file, "1px.png")}
            response = self.client.post("/images/resize_avatar", data=data)
        self.assertEqual(response.status_code, 200)

        resp = response.json

        self.assertIn("avatar24", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar24"]["body"])))
        self.assertEqual(im.size, (24, 24))
        self.assertEqual(im.format, "PNG")

        self.assertIn("avatar48", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar48"]["body"])))
        self.assertEqual(im.size, (48, 48))
        self.assertEqual(im.format, "PNG")

        self.assertIn("avatar73", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar73"]["body"])))
        self.assertEqual(im.size, (73, 73))
        self.assertEqual(im.format, "PNG")

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
        self.assertEqual(im.format, "PNG")

        self.assertIn("avatar48", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar48"]["body"])))
        self.assertEqual(im.size, (48, 48))
        self.assertEqual(im.format, "PNG")

        self.assertIn("avatar73", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar73"]["body"])))
        self.assertEqual(im.size, (73, 73))
        self.assertEqual(im.format, "PNG")

        self.assertIn("avatar128", resp)
        im = Image.open(io.BytesIO(base64.b64decode(resp["avatar128"]["body"])))
        self.assertEqual(im.size, (128, 128))
        self.assertEqual(im.format, "PNG")

        self.assertNotIn("avatar256", resp)
        self.assertNotIn("avatar512", resp)
