import base64
import io
import json
import os
import subprocess
import tempfile

import magic
from flask import Blueprint, request
from PIL import Image, ImageStat
from sentry_sdk import capture_exception

from remote.wrapper import APIDoc, APIError, Methods, api_doc, error, success

# Please keep the blueprint definition at the top uniformly.
video_bp = Blueprint("video", __name__)

# The site takes videos up to 95 MB; this leaves room for the multipart envelope.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# The containers taken, by the MIME type libmagic sees, and the extension each one
# is served with.
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}

# Every ffmpeg run reads one local file through one of these two demuxers and
# nothing else. A playlist (HLS, concat) passed off as a video would otherwise have
# ffmpeg open the files or URLs it lists.
INPUT_GUARD = ["-protocol_whitelist", "file", "-format_whitelist", "mov,matroska"]
FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# Seconds. All runs together stay under gunicorn's 30 second worker timeout.
PROBE_TIMEOUT = 5
GRAB_TIMEOUT = 4

# A frame darker or flatter than this (mean and spread of its luma, 0-255) counts
# as black.
DARK_MEAN = 20
FLAT_STDDEV = 6


@video_bp.route("/videos/poster", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload a video (MP4, MOV or WebM) and get its info, "
        "and a JPEG poster frame that is not black"
    )
)
def poster():
    if not request.content_length or request.content_length > MAX_UPLOAD_BYTES:
        return error(APIError(message="The video is too large"), status=413)
    if not (uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))

    with tempfile.NamedTemporaryFile() as video:
        uploaded.save(video)
        video.flush()
        path = video.name

        ext = VIDEO_TYPES.get(magic.from_file(path, mime=True))
        if ext is None:
            return error(APIError(message="Not an MP4, MOV or WebM video"))

        try:
            info = _probe(path)
        except subprocess.TimeoutExpired as e:
            capture_exception(e)
            return error(APIError(message="Reading the video took too long"))
        except (subprocess.CalledProcessError, ValueError):
            return error(APIError(message="Unable to read the video"))

        # Not the cover art an audio file can carry as a one-frame "video".
        pictures = [
            s for s in info.get("streams", []) if s.get("codec_type") == "video"
        ]
        stream = next(
            (s for s in pictures if not s.get("disposition", {}).get("attached_pic")),
            None,
        )
        if stream is None:
            return error(APIError(message="The file has no video"))
        audio = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "audio"),
            {},
        )
        try:
            duration = max(float(info.get("format", {}).get("duration", 0)), 0)
        except ValueError:
            duration = 0

        frame, at = _poster(path, stream["index"], duration)
        if frame is None:
            return error(APIError(message="Unable to read a frame of the video"))
        size = os.path.getsize(path)

    with Image.open(io.BytesIO(frame)) as image:
        width, height = image.size
    return success(
        {
            "status": "ok",
            "success": True,
            "mime_type": next(m for m, e in VIDEO_TYPES.items() if e == ext),
            "ext": ext,
            "binary_size": size,
            "duration": duration,
            # Of the poster, so a phone's portrait video is as tall as it plays.
            "width": width,
            "height": height,
            "video_codec": stream.get("codec_name", ""),
            "audio_codec": audio.get("codec_name", ""),
            "poster": base64.b64encode(frame).decode("utf-8"),
            "poster_at": at,
        }
    )


def _probe(path: str) -> dict:
    """Read the file's container and streams with ffprobe."""
    done = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            *INPUT_GUARD,
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name"
            ":stream_disposition=attached_pic",
            "-of",
            "json",
            "file:" + path,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=PROBE_TIMEOUT,
        check=True,
    )
    return json.loads(done.stdout)


def _grab(path: str, stream: int, at: float) -> bytes | None:
    """Grab the keyframe at or before `at` seconds as a JPEG, decoding only it."""
    try:
        done = subprocess.run(
            [
                FFMPEG,
                "-nostdin",
                "-v",
                "error",
                *INPUT_GUARD,
                "-threads",
                "2",
                "-skip_frame",
                "nokey",
                "-noaccurate_seek",
                "-ss",
                f"{at:.3f}",
                "-i",
                "file:" + path,
                "-map",
                f"0:{stream}",
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GRAB_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        capture_exception(e)
        return None
    return done.stdout or None


def _poster(path: str, stream: int, duration: float) -> tuple[bytes | None, float]:
    """Pick the first frame that is not black, from a few points early on.

    A video that is all dark gets its brightest sampled frame instead.
    """
    if duration:
        early = (0, 1, duration * 0.1, duration * 0.25, duration * 0.5)
        points = {t for t in early if t < duration}
    else:
        # No duration in the container: seeking past the end only finds no frame.
        points = {0, 1, 3, 5}

    brightest = None
    for at in sorted(points):
        frame = _grab(path, stream, at)
        if frame is None:
            continue
        try:
            with Image.open(io.BytesIO(frame)) as image:
                luma = ImageStat.Stat(image.convert("L").resize((64, 64)))
        except Exception as e:  # noqa
            capture_exception(e)
            continue
        mean, spread = luma.mean[0], luma.stddev[0]
        if mean >= DARK_MEAN and spread >= FLAT_STDDEV:
            return frame, at
        if brightest is None or mean > brightest[0]:
            brightest = (mean, frame, at)
    if brightest is None:
        return None, 0
    return brightest[1], brightest[2]
