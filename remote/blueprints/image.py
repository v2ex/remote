import base64
import io
import time
from dataclasses import dataclass
from typing import Iterable, List, Tuple

import pillow_avif  # noqa: F401
from flask import Blueprint, request
from PIL import Image
from resizeimage import resizeimage
from sentry_sdk import capture_exception

from remote.utilities.image import AvatarSize, ExifTag, ImageHandle, ImageMIME
from remote.wrapper import APIDoc, APIError, Methods, api_doc, error, success

# Please keep the blueprint definition at the top uniformly.
image_bp = Blueprint("image", __name__)


@dataclass
class ImageInfo:
    status: str = "ok"
    success: bool = True
    width: int = 0
    height: int = 0
    mime_type: str = ""
    binary_size: int = 0
    frames: int = 1


@image_bp.route("/images/info", methods=Methods.common())
@api_doc(APIDoc(usage="Upload an image file and show its info like size and type"))
def images_info():
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    img = handler.image

    return success(
        ImageInfo(
            width=img.size[0],
            height=img.size[1],
            mime_type=handler.mime.mime,
            binary_size=handler.raw_size,
            frames=handler.frames,
        )
    )


@image_bp.route("/images/prepare_jpeg", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload an image file in JPEG format "
        "and have its GPS info stripped, and auto rotated"
    )
)
def prepare_jpeg():
    # Check uploaded file is valid or not.
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    if handler.mime != ImageMIME.JPEG:
        err = APIError(message="This endpoint is only for processing JPEG images")
        return error(err)

    # Now we have a valid JPEG.
    # Two things to do:
    #
    # 1. Remove GPS
    # 2. Auto Rotate
    try:
        handler.auto_rotate().remove_exif(ExifTag.GPS_INFO)
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to prepare image: {e}"), status=500)
    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.mime.mime,
            },
            "status": "ok",
            "output": handler.b64_content,
            "success": True,
        }
    )


@image_bp.route("/images/fit/<int:box>", methods=Methods.common())
@api_doc(
    APIDoc(usage="Upload an image file and fit it into a box of the specified size")
)
def fit(box: int):
    # Check uploaded file is valid or not.
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    # Now we have a valid image.
    # Fit it into a box of the specified size.
    _image = handler.image

    start = time.time()
    _resized_content = _rescale_aspect_ratio(_image, box)
    if _resized_content is None:
        return error(APIError(message="Error occurred during rescaling"), status=500)
    resized_content = base64.b64encode(_resized_content).decode("utf-8")
    end = time.time()

    if request.args.get("simple"):
        return success(resized_content, mimetype=handler.guess_mime.mime)

    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.mime.mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            "output": resized_content,
        }
    )


@image_bp.route("/images/resize_avatar", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload an image file in supported format, and resize for website "
        f"avatars in the following sizes: {AvatarSize.supported_desc()}. "
        f"Supported formats are: {', '.join(ImageMIME.all())}"
    )
)
def resize_avatar():
    # Check uploaded file is valid or not.
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    # Now we have a valid image, and we know its size and type.
    # Resize it to each size contained in `AvatarSize`.

    start = time.time()
    avatars = {}
    try:
        # Confirmation basic avatar to resize.
        # Try to use max size avatar otherwise use original(rotated).
        if not handler.animated:
            handler.auto_rotate()

        image = handler.image
        for size in AvatarSize:
            if size.is_mandatory or _need_rescale(image, size):
                # Choose rescale function based on format and animation.
                if handler.animated:
                    if handler.mime == ImageMIME.GIF:
                        frames, durations = _rescale_animated_gif_frames(image, size)
                    elif handler.mime == ImageMIME.WEBP:
                        frames, durations = _rescale_animated_webp_frames(image, size)
                    elif handler.mime == ImageMIME.PNG:
                        frames, durations = _rescale_animated_png_frames(image, size)
                    else:
                        frames = None

                    if frames:
                        data = _save_animated_frames_data(
                            frames,
                            durations,
                            format="PNG",
                            loop=0,  # always loop for avatar
                            default_image=False,
                            optimize=True,
                        )
                    else:
                        # Fallback to first frame of animated image
                        data = _rescale_single_frame_avatar(image, size)
                else:
                    data = _rescale_single_frame_avatar(image, size)
                avatars[f"avatar{size}"] = {
                    "size": len(data),
                    "body": base64.b64encode(data).decode("utf-8"),
                }
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to resize the uploaded image file: {e}"))
    end = time.time()

    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.mime.mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            **avatars,
        }
    )


def get_file_bytes() -> APIError | bytes:
    if not (_uploaded := request.files.get("file")):
        return APIError(message="No file was uploaded")
    return _uploaded.read()


def _need_rescale(img: Image.Image, target_size: int) -> bool:
    """Rescale an image if each of its both dimensions is larger than target size."""
    return img.size[0] >= target_size and img.size[1] >= target_size


def _rescale_single_frame_avatar(
    image: Image.Image, size: AvatarSize
) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            rescaled = resizeimage.resize_cover(image, (size, size), validate=False)
            rescaled.save(io_obj, format="PNG")
            return io_obj.getvalue()

    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_animated_png_frames(
    image: Image.Image, size: int
) -> Tuple[List[Image.Image], List[float]]:
    frames = []
    durations = []
    # TODO: process default_image when resizing
    # https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#apng-sequences
    frame_start = 0
    if image.info.get("default_image", False):
        frame_start = 1

    for i in range(frame_start, image.n_frames):
        image.seek(i)
        frames.append(resizeimage.resize_cover(image, (size, size), validate=False))
        durations.append(image.info.get("duration", 0))

    return frames, durations


def _rescale_animated_webp_frames(
    image: Image.Image, size: int
) -> Tuple[List[Image.Image], List[float]]:
    frames = []
    durations = []
    for i in range(image.n_frames):
        image.seek(i)
        frames.append(resizeimage.resize_cover(image, (size, size), validate=False))
        durations.append(image.info.get("duration", 0))

    return frames, durations


def _rescale_animated_gif_frames(
    image: Image.Image, size: int
) -> Tuple[List[Image.Image], List[float]]:
    """
    Rescale animated GIF image.

    Adpated from:
    - https://gist.github.com/BigglesZX/4016539
    - https://github.com/Alejandroacho/ScaleGif/blob/master/scale_gif.py

    GIF animation needs special handling as GIF frames can be either full, or additive
    over previous frames.

    Pre-process pass over the image to determine the mode (full or additive).
    Necessary as assessing single frames isn't reliable. Need to know the mode
    before processing all frames.
    """
    additive = False

    for i in range(image.n_frames):
        image.seek(i)
        if image.tile:
            tile = image.tile[0]
            update_region = tile[1]
            update_region_dimensions = update_region[2:]
            if update_region_dimensions != image.size:
                additive = True

    frames = []
    durations = []
    image.seek(0)
    global_palette = image.getpalette()
    last_frame = image.convert("RGBA")

    for i in range(image.n_frames):
        # If the GIF uses local colour tables, each frame will have its own palette.
        # If not, we need to apply the global palette to the new frame.
        image.seek(i)
        if not image.getpalette():
            image.putpalette(global_palette)

        new_frame = Image.new("RGBA", image.size)
        if additive:
            # Copy last frame to apply update
            new_frame.paste(last_frame)
        # TODO: confirm whether it should really paste to (0, 0) or not?
        new_frame.paste(image, (0, 0), image.convert("RGBA"))

        frames.append(resizeimage.resize_cover(image, (size, size), validate=False))
        durations.append(image.info.get("duration", 0))
        last_frame = new_frame

    return frames, durations


def _save_animated_frames_data(
    frames: Iterable[Image.Image], durations: Iterable[float], format: str, **info
) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            frames[0].save(
                io_obj,
                format=format,
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                **info,
            )
            return io_obj.getvalue()
    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_aspect_ratio(image: Image.Image, size: int) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            rescale = resizeimage.resize_thumbnail(image, (size, size))
            rescale.save(io_obj, format=image.format)
            return io_obj.getvalue()
    except Exception as e:  # noqa
        capture_exception(e)
        return
