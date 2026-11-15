import base64
import io
import json
import os
import resource
import subprocess
import tempfile
import time

import magic
from flask import Blueprint, request, send_file
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

# The codecs taken, by ffprobe's name: what browsers play, from phones, cameras
# and screen recorders. Anything else (Motion-JPEG, which keeps each frame's
# EXIF and GPS, or an obscure decoder an attacker picks) is turned away.
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1"}
AUDIO_CODECS = {
    "aac", "mp3", "opus", "vorbis", "ac3", "eac3", "alac", "flac",
    "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_f32le",
}  # fmt: skip
# The decoders those open in this image's ffmpeg (`ffmpeg -decoders`), and the
# ones probing a file's subtitles and cover art opens. Those streams are never
# kept, and a Motion-JPEG video is still turned away by VIDEO_CODECS.
DECODERS = (
    "h264,hevc,vp8,vp9,libdav1d,aac,mp3float,mp3,opus,vorbis,ac3,eac3,alac,flac,"
    "pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_f32le,"
    "mov_text,webvtt,subrip,ass,png,mjpeg"
)

# Every ffmpeg run reads one local file through one of these two demuxers and
# nothing else. A playlist (HLS, concat) passed off as a video would otherwise have
# ffmpeg open the files or URLs it lists. No other decoder can be opened either.
INPUT_GUARD = [
    "-protocol_whitelist", "file",
    "-format_whitelist", "mov,matroska",
    "-codec_whitelist", DECODERS,
]  # fmt: skip
FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# Seconds. All runs together stay under gunicorn's 30 second worker timeout.
PROBE_TIMEOUT = 5
GRAB_TIMEOUT = 4
POSTER_BUDGET = 24
PREPARE_TIMEOUT = 20

# Address space for one ffprobe or ffmpeg run. A sample table of millions of
# entries in a small file would otherwise take a gigabyte to index.
PROBE_MEMORY = 1024 * 1024 * 1024
FFMPEG_MEMORY = 2 * 1024 * 1024 * 1024

# Bigger than 8K (7680x4320), or more samples than a 95 MB video holds, isn't
# a video anyone shares.
MAX_PIXELS = 8192 * 4320
MAX_SAMPLES = 2_000_000
# The poster is the size a page shows it at most.
POSTER_MAX_SIDE = 3840

# A remux copies the samples a file lists, and a sample table can list one
# chunk thousands of times: the copy may only be this much bigger than the upload.
PREPARE_SLACK = 1024 * 1024

# What -bsf drops from each codec's bitstream on the way through: SEI messages
# (H.264 NAL type 6, HEVC 39 and 40) and AV1 metadata OBUs (type 5), where an
# encoder may write anything, a location included.
METADATA_UNITS = {
    "h264": "filter_units=remove_types=6",
    "hevc": "filter_units=remove_types=39|40",
    "av1": "filter_units=remove_types=5",
}

# The muxer each kind of video is written back with.
MUXERS = {"mp4": "mp4", "mov": "mov", "webm": "webm"}

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

        info, problem = _checked_probe(path)
        if problem:
            return error(problem)
        stream = _videos(info)[0]
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
        # Of the frame as it plays, so a phone's portrait video is as tall as it
        # plays.
        width, height = image.size
        if max(width, height) > POSTER_MAX_SIDE:
            image.thumbnail((POSTER_MAX_SIDE, POSTER_MAX_SIDE))
            smaller = io.BytesIO()
            image.save(smaller, "JPEG", quality=90)
            frame = smaller.getvalue()
        poster_width, poster_height = image.size
    return success(
        {
            "status": "ok",
            "success": True,
            "mime_type": next(m for m, e in VIDEO_TYPES.items() if e == ext),
            "ext": ext,
            "binary_size": size,
            "duration": duration,
            "width": width,
            "height": height,
            "video_codec": stream.get("codec_name", ""),
            "audio_codec": audio.get("codec_name", ""),
            "poster": base64.b64encode(frame).decode("utf-8"),
            "poster_width": poster_width,
            "poster_height": poster_height,
            "poster_at": at,
        }
    )


@video_bp.route("/videos/prepare", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload a video (MP4, MOV or WebM) and get it back without its "
        "metadata: no location, dates or data tracks, its video and audio as they are"
    )
)
def prepare():
    if not request.content_length or request.content_length > MAX_UPLOAD_BYTES:
        return error(APIError(message="The video is too large"), status=413)
    if not (uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))

    with tempfile.NamedTemporaryFile() as video:
        uploaded.save(video)
        video.flush()
        ext = VIDEO_TYPES.get(magic.from_file(video.name, mime=True))
        if ext is None:
            return error(APIError(message="Not an MP4, MOV or WebM video"))
        info, problem = _checked_probe(video.name)
        if problem:
            return error(problem)
        # -map 0:V keeps the videos in this order, as output streams 0, 1, ...
        units = []
        for i, stream in enumerate(_videos(info)):
            if stream.get("codec_name") in METADATA_UNITS:
                units += [f"-bsf:v:{i}", METADATA_UNITS[stream["codec_name"]]]
        limit = os.path.getsize(video.name) + PREPARE_SLACK
        # Closing it after the response is sent deletes it.
        out = tempfile.NamedTemporaryFile(suffix="." + ext)
        try:
            _run(
                [
                    FFMPEG,
                    "-nostdin",
                    "-y",
                    "-v",
                    "error",
                    *INPUT_GUARD,
                    "-i",
                    "file:" + video.name,
                    # Only the pictures and the sound: an iPhone's timed
                    # metadata track goes too.
                    "-map",
                    "0:V",
                    "-map",
                    "0:a?",
                    "-c",
                    "copy",
                    *units,
                    "-map_metadata",
                    "-1",
                    "-map_chapters",
                    "-1",
                    *(["-movflags", "+faststart"] if ext != "webm" else []),
                    # Stops writing past the limit; checked below.
                    "-fs",
                    str(limit),
                    "-f",
                    MUXERS[ext],
                    "file:" + out.name,
                ],
                timeout=PREPARE_TIMEOUT,
                memory=FFMPEG_MEMORY,
            )
        except subprocess.TimeoutExpired as e:
            out.close()
            capture_exception(e)
            return error(APIError(message="Preparing the video took too long"))
        except subprocess.CalledProcessError:
            out.close()
            return error(APIError(message="Unable to read the video"))
        if os.path.getsize(out.name) >= limit:
            out.close()
            return error(APIError(message="Unable to read the video"))

    mime_type = next(m for m, e in VIDEO_TYPES.items() if e == ext)
    return send_file(out, mimetype=mime_type)


def _run(args: list, timeout: float, memory: int, check: bool = True):
    """Run ffmpeg or ffprobe with at most `memory` bytes of address space."""

    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))

    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=check,
        preexec_fn=limit,
    )


def _probe(path: str) -> dict:
    """Read the file's container and streams with ffprobe."""
    done = _run(
        [
            FFPROBE,
            "-v",
            "error",
            *INPUT_GUARD,
            "-threads",
            "1",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,nb_frames"
            ":stream_disposition=attached_pic",
            "-of",
            "json",
            "file:" + path,
        ],
        timeout=PROBE_TIMEOUT,
        memory=PROBE_MEMORY,
    )
    return json.loads(done.stdout)


def _videos(info: dict) -> list:
    """List the video streams.

    Cover art, which a file can carry as a one-frame "video", isn't one.
    """
    return [
        s
        for s in info.get("streams", [])
        if s.get("codec_type") == "video"
        and not s.get("disposition", {}).get("attached_pic")  # noqa: W503
    ]


def _checked_probe(path: str) -> tuple[dict, APIError | None]:
    """Probe the file, and say what turns it away.

    That is no video, a codec off the lists, or a size no shared video has.
    """
    try:
        info = _probe(path)
    except subprocess.TimeoutExpired as e:
        capture_exception(e)
        return {}, APIError(message="Reading the video took too long")
    except (subprocess.CalledProcessError, ValueError):
        return {}, APIError(message="Unable to read the video")

    videos = _videos(info)
    if not videos:
        return info, APIError(message="The file has no video")
    for s in info.get("streams", []):
        kind, codec = s.get("codec_type"), s.get("codec_name")
        if (kind == "video" and s in videos and codec not in VIDEO_CODECS) or (
            kind == "audio" and codec not in AUDIO_CODECS
        ):
            return info, APIError(message=f"Unsupported {kind} codec: {codec}")
    try:
        pixels = max(int(s.get("width", 0)) * int(s.get("height", 0)) for s in videos)
        samples = sum(int(s.get("nb_frames", 0) or 0) for s in info["streams"])
    except (TypeError, ValueError):
        return info, APIError(message="Unable to read the video")
    if pixels > MAX_PIXELS or samples > MAX_SAMPLES:
        return info, APIError(message="The video is too large")
    return info, None


def _grab(path: str, stream: int, at: float, timeout: float) -> bytes | None:
    """Grab the keyframe at or before `at` seconds as a JPEG, decoding only it."""
    try:
        done = _run(
            [
                FFMPEG,
                "-nostdin",
                "-v",
                "error",
                *INPUT_GUARD,
                "-threads",
                "2",
                "-filter_threads",
                "1",
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
                "-threads",
                "1",
                "-q:v",
                "2",
                "-",
            ],
            timeout=timeout,
            memory=FFMPEG_MEMORY,
            check=False,
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
    # The probe has had its share of the 30 seconds.
    deadline = time.monotonic() + POSTER_BUDGET - PROBE_TIMEOUT
    for at in sorted(points):
        left = deadline - time.monotonic()
        if left < 1:
            break
        frame = _grab(path, stream, at, min(GRAB_TIMEOUT, left))
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
