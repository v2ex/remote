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
    def get_by_magic_format(cls, value: str) -> "ImageMIME":
        return next((i for i in cls if i.value[0] == value), None)

    @classmethod
    def get_by_pil_format(cls, value: str) -> "ImageMIME":
        return next((i for i in cls if i.value[1] == value), None)


class ExifTag(Enum):
    """View more tags from `PIL.ExifTags.TAGS`."""

    ORIENTATION = 0x0112
    # see more about magic number `0x8825` from
    # [Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/8.2.0.html#image-getexif-exif-and-gps-ifd)
    GPS_INFO = 0x8825
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
    # Side of the square canvas SVG is rasterized to, in pixels.
    # Twice the largest avatar, so that every avatar size is a downscale.
    SVG_CANVAS_SIDE = 2 * max(AvatarSize)

    def __init__(self, content: bytes):
        """Image handle."""
        self._raw_content: bytes = content
        self.mime: Optional[ImageMIME] = None
        self.image: Image.Image = None
        self.preprocess()

    @property
    def is_valid(self) -> bool:
        return self.mime is not None and self.image is not None

    @property
    def is_animated(self) -> bool:
        return getattr(self.image, "is_animated", False)

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
        """Convert rare image formats into formats supported by PIL."""
        self.mime = self.guess_mime_from_bytes(self._raw_content)
        if not self.mime:
            current_app.logger.info("No MIME type found, skip the preparation process.")
            return

        # PIL only support rasterized image formats, convert SVG to PNG first.
        raw_content = self._raw_content
        if self.mime == ImageMIME.SVG:
            try:
                raw_content = self.rasterize_svg(self._raw_content)
            except Exception as e:  # noqa
                capture_exception(e)

        try:
            image = self.load_from_bytes(raw_content)
        except Exception:  # noqa
            current_app.logger.error("Failed to load image from bytes.")
            return

        # Preprocess rare image types.
        ico_mimes = [
            ImageMIME.ICO,
            ImageMIME.ICO_UNOFFICIAL,
            ImageMIME.ICNS,
            ImageMIME.X_ICNS,
        ]
        if self.mime in ico_mimes:
            # Integer scaling for ICO icons.
            max_size = max(AvatarSize)
            self.image = image.resize((max_size, max_size), Image.NEAREST)
            self.image.format = ImageMIME.PNG.pil_format
        else:
            self.image = image
            self.image.format = self.mime.pil_format

    @staticmethod
    def guess_mime_from_bytes(buffer: bytes) -> ImageMIME | None:
        """Try to guess the mime type from bytes content by `magic` or `PIL`."""
        magic_format = pil_format = None
        try:
            magic_format = magic.from_buffer(buffer, mime=True)
            # magic_format eg: "image/jpeg"
        except magic.MagicException:
            current_app.logger.warning("Magic unable to guess mime type", exc_info=True)

        if magic_format and (
            mime := ImageMIME.get_by_magic_format(magic_format.lower())
        ):
            return mime

        try:
            with Image.open(io.BytesIO(buffer)) as _image:
                pil_format = _image.format
            # pil_format eg: "AVIF"
        except Exception:  # noqa
            # Whatever PIL cannot open is not an image we can work with.
            # It gets logged below, together with what magic made of it.
            ...

        if pil_format and (mime := ImageMIME.get_by_pil_format(pil_format.upper())):
            return mime

        current_app.logger.warning(
            "Unsupported mime type, magic: %s, PIL :%s", magic_format, pil_format
        )

    @staticmethod
    def rasterize_svg(svg: bytes) -> bytes:
        """
        Convert untrusted SVG to a square PNG with the drawing centered in it.

        - `unsafe=False` keeps the document from reaching anything but itself: no XML
          entities, and no fetching of external URLs or local files (CairoSVG 2.7.0+,
          see `requirements.txt`).
        - The canvas size is ours. An SVG declares its own size, so rendering it at
          that size would let a few bytes like `width="30000" height="30000"` make us
          allocate gigabytes. Being vector, it loses nothing by being scaled instead.
        """
        return cairosvg.svg2png(
            svg,
            dpi=300,
            unsafe=False,
            output_width=ImageHandle.SVG_CANVAS_SIDE,
            output_height=ImageHandle.SVG_CANVAS_SIDE,
        )

    @staticmethod
    def load_from_bytes(bytes_content: bytes) -> Image.Image:
        """Convert bytes content to `PIL.Image`."""
        return Image.open(io.BytesIO(bytes_content))

    def remove_exif(self, *tags: ExifTag, full: bool = False):
        """Remove GPS data from the image EXIF."""
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

    # See also: https://stackoverflow.com/questions/33533148/
    def auto_rotate(self):
        """Auto-rotate the image according to its EXIF data."""
        if not self.image:
            current_app.logger.warning("No image found, skip auto rotate.")
            return
        self.image = ImageOps.exif_transpose(self.image)
        return self
