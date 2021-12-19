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
    image = handler.image

    start = time.time()
    if handler.animated and request.args.get("animated"):
        if handler.mime == ImageMIME.GIF:
            frames, durations = _rescale_animated_image_frames(
                image, box, resizeimage.resize_thumbnail
            )
            info = {
                key: image.info[key]
                for key in ["loop", "transparency"]
                if key in image.info
            } | {
                "optimize": True,
            }
        elif handler.mime == ImageMIME.WEBP:
            frames, durations = _rescale_animated_image_frames(
                image, box, resizeimage.resize_thumbnail
            )
            info = {
                key: image.info[key]
                for key in ["loop", "icc_profile"]
                if key in image.info
            } | {
                "lossless": False,
                "optimize": True,
            }
        elif handler.mime == ImageMIME.PNG:
            frames, durations = _rescale_animated_png_frames(
                image, box, resizeimage.resize_thumbnail
            )
            info = {key: image.info[key] for key in ["loop"] if key in image.info} | {
                "optimize": True,
                "default_image": False,
            }
        else:
            frames = None

        if frames:
            data = _save_animated_frames_data(
                frames, durations, format=handler.mime.pil_format, **info
            )
        else:
            # Fallback to first frame of animated image
            data = _rescale_single_frame_image(
                image, box, handler.mime.pil_format, resizeimage.resize_thumbnail
            )
    else:
        data = _rescale_single_frame_image(
            image, box, handler.mime.pil_format, resizeimage.resize_thumbnail
        )
    if data is None:
        return error(APIError(message="Error occurred during rescaling"), status=500)
    resized_content = base64.b64encode(data).decode("utf-8")
    end = time.time()

    if request.args.get("simple"):
        return success(resized_content, mimetype=handler.mime.mime)

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
                if handler.animated and request.args.get("animated"):
                    if handler.mime == ImageMIME.GIF or handler.mime == ImageMIME.WEBP:
                        frames, durations = _rescale_animated_image_frames(
                            image, size, resizeimage.resize_cover, validate=False
                        )
                    elif handler.mime == ImageMIME.PNG:
                        frames, durations = _rescale_animated_png_frames(
                            image, size, resizeimage.resize_cover, validate=False
                        )
                    else:
                        frames = None

                    if frames:
                        data = _save_animated_frames_data(
                            frames,
                            durations,
                            format=ImageMIME.PNG.pil_format,
                            loop=0,  # always loop for avatar
                        )
                    else:
                        # Fallback to first frame of animated image
                        data = _rescale_single_frame_image(
                            image,
                            size,
                            ImageMIME.PNG.pil_format,
                            resizeimage.resize_cover,
                            validate=False,
                        )
                else:
                    data = _rescale_single_frame_image(
                        image, size, resizeimage.resize_cover, validate=False
                    )
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


def _rescale_single_frame_image(
    image: Image.Image, size: int, format: str, resize, **resize_kwargs
) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            rescaled = resize(image, (size, size), **resize_kwargs)
            rescaled.save(io_obj, format=format)
            return io_obj.getvalue()

    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_animated_png_frames(
    image: Image.Image, size: int, resize, **resize_kwargs
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
        frames.append(resize(image, (size, size), **resize_kwargs))
        durations.append(image.info.get("duration", 0))

    return frames, durations


def _rescale_animated_image_frames(
    image: Image.Image, size: int, resize, **resize_kwargs
) -> Tuple[List[Image.Image], List[float]]:
    # GIF _should_ no longer need special handling on partial/additive frames
    # See https://gist.github.com/BigglesZX/4016539 for old reference
    frames = []
    durations = []
    for i in range(image.n_frames):
        image.seek(i)
        frames.append(resize(image, (size, size), **resize_kwargs))
        durations.append(image.info.get("duration", 0))
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
