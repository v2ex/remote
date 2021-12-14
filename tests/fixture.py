class TestFixture:
    @staticmethod
    def get_fixture_path(uri):
        return f"tests/fixtures/{uri}"

    @property
    def hello_jpeg(self):
        return self.get_fixture_path("hello.jpeg")

    @property
    def hello_png(self):
        return self.get_fixture_path("hello.png")

    @property
    def test_webp(self):
        return self.get_fixture_path("test.webp")

    @property
    def animated_gif(self):
        return self.get_fixture_path("animated.gif")

    @property
    def cap_avif(self):
        return self.get_fixture_path("cap.avif")

    @property
    def python_svg(self):
        return self.get_fixture_path("python.svg")

    @property
    def px1_png(self):
        return self.get_fixture_path("1px.png")

    @property
    def px200_jpg(self):
        return self.get_fixture_path("200px.jpg")

    @property
    def sunny_icns(self):
        return self.get_fixture_path("sunny.icns")
