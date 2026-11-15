import base64
import io

from PIL import Image, ImageStat

from tests.fixture import TestFixture
from tests.test_app import TestBase


class TestVideo(TestBase, TestFixture):
    def test_poster_skips_a_black_opening(self):
        with open(self.black_start_mp4, "rb") as video:
            response = self.client.post(
                "/videos/poster", data={"file": (video, "clip.mp4")}
            )
        self.assertEqual(response.status_code, 200)

        resp = response.json
        self.assertEqual(resp["ext"], "mp4")
        self.assertEqual(resp["video_codec"], "h264")
        self.assertEqual((resp["width"], resp["height"]), (64, 48))
        with Image.open(io.BytesIO(base64.b64decode(resp["poster"]))) as poster:
            self.assertEqual(poster.format, "JPEG")
            self.assertGreater(ImageStat.Stat(poster.convert("L")).mean[0], 20)

    def test_poster_refuses_a_playlist_named_as_a_video(self):
        playlist = (
            b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\n"
            b"file:///etc/passwd\n#EXT-X-ENDLIST\n"
        )
        response = self.client.post(
            "/videos/poster", data={"file": (io.BytesIO(playlist), "clip.mp4")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("poster", response.json)
