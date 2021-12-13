import base64
import io
from enum import Enum, IntEnum, unique
from typing import Optional

import cairosvg
import magic
from flask import current_app
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from sentry_sdk import capture_exception

# To support HEIC/HEIF images.
register_heif_opener()


class ImageMIME(Enum):
    """
    Image MIME types.

    See more details from image part of page:
    [Media Types](https://www.iana.org/assignments/media-types/media-types.xhtml)
    """

    # The following mimes is ref from `PIL.IMAGE.MIME`
    BMP = "image/bmp", "BMP"
    DIB = "image/bmp", "BMP"
    GIF = "image/gif", "GIF"
    TIFF = "image/tiff", "TIFF"
    JPEG = "image/jpeg", "JPEG"
    PNG = "image/png", "PNG"
    JPEG2000 = "image/jp2", "JPEG2000"
    ICNS = "image/icns", "ICNS"
    # This format is similar to `ICO_UNOFFICIAL` below.
    # It's an **unofficial** icon format(not registered in IANA).
    # But it is widely used, we should regard the two as the same.
    # See `ICO_UNOFFICIAL` format below for comparison.
    ICO = "image/x-icon", "ICO"
    PSD = "image/vnd.adobe.photoshop", "PSD"
    WEBP = "image/webp", "WEBP"

    # No test yet.
    # PPM = "image/x-portable-anymap", "PPM"
    # PCX = "image/x-pcx", "PCX"
    # # EPS = "application/postscript", "EPS"  # not supported application now.
    # MPEG = "video/mpeg", "MPEG"
    # MPO = "image/mpo", "MPO"
    # PALM = "image/palm", "PALM"
    # # PDF = "application/pdf", "PDF"  # not supported application now.
    # SGI = "image/sgi", "SGI"
    # TGA = "image/x-tga", "TGA"
    # XBM = "image/xbm", "XBM"
    # XPM = "image/xpm", "XPM"

    #  Additional support by us.
    AVIF = "image/avif", "AVIF"
    HEIF = "image/heif", "HEIF"
    HEIC = "image/heic", "HEIC"
    # [Apple Icon Image format](https://en.wikipedia.org/wiki/Apple_Icon_Image_format)
    X_ICNS = "image/x-icns", "ICNS"
    SVG = "image/svg+xml", "PNG"
    # This format is similar to `ICO` above.
    # It is an **official** icon format(registered in IANA).
    # But not commonly used, instead, we use `ICO` more.
    # See `ICO` format above for comparison.
    ICO_UNOFFICIAL = "image/vnd.microsoft.icon", "ICO"
    ...

    def __init__(self, mime, pil_format=""):
        """All supported image MIME types by us."""
        self.mime = mime
        self.pil_format = pil_format

    @classmethod
    def all(cls):
        return [i.value[0] for i in cls]

    @classmethod
    def get_by_value(cls, value: str) -> "ImageMIME":
        return next((i for i in cls if i.value[0] == value), None)


class ExifTag(Enum):
    """View more tags from `PIL.ExifTags.TAGS`."""

    Orientation = 0x0112
    # see more about magic number `0x8825` from
    # [Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/8.2.0.html#image-getexif-exif-and-gps-ifd)
    GPSInfo = 0x8825
    ...


@unique
class AvatarSize(IntEnum):
    MINI = 24
    NORMAL = 48
    LARGE = 73
    XL = 128
    XXL = 256
    XXXL = 512

    @classmethod
    def supported_desc(cls):
        return " / ".join(f"{i}x{i}" for i in cls)

    @property
    def is_mandatory(self):
        return self in [
            self.MINI.value,
            self.NORMAL.value,
            self.LARGE.value,
        ]


class ImageHandle:
    def __init__(self, content: bytes):
        """Image handle."""
        self._raw_content: bytes = content
        self.guess_mime: Optional[ImageMIME] = None
        self.image: Image = None
        self.preprocess()

    @property
    def is_valid(self) -> bool:
        return self.guess_mime is not None and self.image is not None

    @property
    def raw_size(self) -> int:
        return len(self._raw_content)

    @property
    def frames(self) -> int:
        return getattr(self.image, "n_frames", 1)

    @property
    def b64_content(self, mime: ImageMIME = ImageMIME.JPEG) -> Optional[str]:
        if self.image is None:
            return None
        with io.BytesIO() as buffered:
            self.image.save(buffered, format=mime.name)
            return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def preprocess(self):
        """
        Convert unusual/difficultly formats to common formats.

        We need to convert some special mimes into formats supported by PIL,
        so that we can handle it conveniently later.
        """
        # You can't do anything else without MIME.
        self.guess_mime = self.guess_mime_from_bytes(self._raw_content)
        if not self.guess_mime:
            current_app.logger.info("No MIME type found, skip ths preparation process.")
            return

        # Some types are not supported by PIL,
        # so we need to unified convert then give them to PIL.
        _raw_content = self._raw_content
        if self.guess_mime == ImageMIME.SVG:
            try:
                _raw_content = cairosvg.svg2png(self._raw_content, dpi=300)
            except Exception as e:  # noqa
                if current_app.config["SENTRY_ENVIRONMENT"] != "production":
                    capture_exception(e)

        # Try to use PIL to load the bytes content to PIL.Image.
        try:
            _image: Image = self.load_from_bytes(_raw_content)
        except Exception:  # noqa
            current_app.logger.error("Failed to load image from bytes.")
            return

        # Some types need preprocessing are convenient for subsequent processing.
        ico_mimes = [
            ImageMIME.ICO.value,
            ImageMIME.ICO_UNOFFICIAL.value,
            ImageMIME.ICNS,
            ImageMIME.X_ICNS,
        ]
        if self.guess_mime in ico_mimes:
            max_size = max(AvatarSize)
            self.image = _image.resize((max_size, max_size), Image.NEAREST)
            self.image.format = ImageMIME.PNG.pil_format
        elif self.guess_mime == ImageMIME.SVG:
            short_size, long_size = min(_image.size), max(_image.size)
            background = Image.new("RGBA", (long_size, long_size), (0, 0, 0, 0))

            # We need to convert SVG to PNG
            is_horizontal = _image.size[0] > _image.size[1]
            _size = int((long_size - short_size) / 2)
            box_size = (0, _size) if is_horizontal else (_size, 0)
            background.paste(_image, box_size)

            self.image = background
            self.image.format = self.guess_mime.pil_format
        else:
            self.image = _image
            self.image.format = self.guess_mime.pil_format

    @staticmethod
    def guess_mime_from_bytes(buffer: bytes) -> ImageMIME | None:
        """Try to guess the mime type from bytes content."""
        try:
            raw_mime = magic.from_buffer(buffer, mime=True)
            # _mime eg: "image/jpeg"
        except magic.MagicException as e:
            current_app.logger.warning("Unable to guess mime type: %s", e.message)
            return

        if not (mime := ImageMIME.get_by_value(raw_mime.lower())):
            current_app.logger.warning("Unsupported mime type: %s", raw_mime)
            return
        return mime

    @staticmethod
    def load_from_bytes(bytes_content: bytes) -> Image:
        """Convert bytes content to `PIL.Image`."""
        return Image.open(io.BytesIO(bytes_content))

    def remove_exif(
        self, *tags: ExifTag, full: bool = False
    ) -> Optional["ImageHandle"]:
        """Remove GPS data from the image EXIF and return a new image."""
        if not self.image:
            current_app.logger.warning("No image found, skip EXIF removing.")
            return
        if full:
            image_without_exif = Image.new(self.image.mode, self.image.size)
            image_without_exif.putdata(list(self.image.getdata()))
            new_image = image_without_exif
            self.image = new_image
        else:
            exif = self.image.getexif() or {}
            for tag in tags:
                exif.pop(tag.value, None)
        return self

    def auto_rotated(self) -> Optional["ImageHandle"]:
        """Auto-rotate the image according to its EXIF data and return a new image."""
        if not self.image:
            current_app.logger.warning("No image found, skip auto rotate.")
            return
        self.image = ImageOps.exif_transpose(self.image)
        return self
