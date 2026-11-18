from __future__ import annotations

import json
import math
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from django.conf import settings
from PIL import Image, ImageFilter, ImageOps

if TYPE_CHECKING:
    from .models import MediaAsset


class MediaRejected(ValueError):
    pass


def process_avatar(asset: MediaAsset, payload: bytes) -> tuple[bytes, bytes]:
    if len(payload) > settings.MEDIA_AVATAR_MAX_BYTES:
        raise MediaRejected("avatar_too_large")
    try:
        with Image.open(BytesIO(payload)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise MediaRejected("avatar_format_invalid")
            width, height = source.size
            if min(width, height) < 200 or max(width, height) > 8000 or width * height > 32000000:
                raise MediaRejected("avatar_dimensions_invalid")
            if getattr(source, "n_frames", 1) != 1:
                raise MediaRejected("avatar_still_photo_required")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except MediaRejected:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise MediaRejected("avatar_invalid") from exc
    if max(image.size) > 2048:
        image = ImageOps.contain(image, (2048, 2048))

    face_box = _find_one_face(image) if settings.MEDIA_REQUIRE_EXACTLY_ONE_FACE else None

    original = BytesIO()
    image.save(original, format="JPEG", quality=90, optimize=True, exif=b"")
    crop_source = _face_crop(image, face_box) if face_box else image
    crop = ImageOps.fit(crop_source, (48, 48), method=Image.Resampling.LANCZOS)
    blurred = crop.filter(ImageFilter.GaussianBlur(radius=3.5)).resize(
        (512, 512), Image.Resampling.BICUBIC
    )
    derived = BytesIO()
    blurred.save(derived, format="JPEG", quality=82, optimize=True, exif=b"")
    return original.getvalue(), derived.getvalue()


def avatar_thumbnail(original: bytes) -> bytes:
    """Small private header image, derived only from a validated original."""
    with Image.open(BytesIO(original)) as source:
        thumbnail = ImageOps.fit(source.convert("RGB"), (256, 256), Image.Resampling.LANCZOS)
        output = BytesIO()
        thumbnail.save(output, format="JPEG", quality=82, optimize=True, exif=b"")
        return output.getvalue()


def _find_one_face(image: Image.Image) -> tuple[int, int, int, int]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise MediaRejected("face_detection_unavailable") from exc
    path = Path(__file__).parent / "resources" / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(path))
    if cascade.empty():
        raise MediaRejected("face_detection_unavailable")
    detection_image = ImageOps.contain(image, (1024, 1024))
    try:
        faces = cascade.detectMultiScale(
            np.array(detection_image.convert("L")), scaleFactor=1.1, minNeighbors=5
        )
    except cv2.error as exc:
        raise MediaRejected("face_detection_unavailable") from exc
    if len(faces) != 1:
        raise MediaRejected("exactly_one_face_required")
    scale = image.width / detection_image.width
    x, y, width, height = [int(value * scale) for value in faces[0]]
    return x, y, width, height


def _face_crop(image: Image.Image, face_box: tuple[int, int, int, int]) -> Image.Image:
    x, y, width, height = face_box
    side = int(max(width, height) * 2.2)
    center_x = x + width // 2
    center_y = y + height // 2
    left = max(0, center_x - side // 2)
    top = max(0, center_y - side // 2)
    right = min(image.width, left + side)
    bottom = min(image.height, top + side)
    left = max(0, right - side)
    top = max(0, bottom - side)
    return image.crop((left, top, right, bottom))


def process_audio(asset: MediaAsset, payload: bytes) -> tuple[bytes, int]:
    if len(payload) > settings.MEDIA_AUDIO_MAX_BYTES:
        raise MediaRejected("audio_too_large")
    with TemporaryDirectory(prefix="anonymoke-media-") as directory:
        source = Path(directory) / "source.m4a"
        output = Path(directory) / "processed.m4a"
        source.write_bytes(payload)
        duration_ms = _audio_duration_ms(source)
        if duration_ms <= 0 or duration_ms > settings.MEDIA_AUDIO_MAX_DURATION_MS:
            raise MediaRejected("audio_duration_invalid")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,mp3,wav",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            *(
                ["-af", "aresample=48000,asetrate=53760,aresample=48000,atempo=0.892857"]
                if asset.disguise_voice
                else []
            ),
            "-map_metadata",
            "-1",
            "-map_metadata:s:a",
            "-1",
            "-map_chapters",
            "-1",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            "-t",
            str(min(15000, settings.MEDIA_AUDIO_MAX_DURATION_MS) / 1000),
            str(output),
        ]
        try:
            subprocess.run(  # noqa: S603 - executable and arguments are fixed constants
                command, check=True, capture_output=True, timeout=30
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MediaRejected("audio_processing_unavailable") from exc
        try:
            processed = output.read_bytes()
        except OSError as exc:
            raise MediaRejected("audio_processing_unavailable") from exc
        if not processed:
            raise MediaRejected("audio_processing_unavailable")
        return processed, min(duration_ms, 15000)


def _audio_duration_ms(path: Path) -> int:
    command = [
        "ffprobe",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "mov,mp3,wav",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - executable and arguments are fixed constants
            command, check=True, capture_output=True, text=True, timeout=10
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid duration")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise MediaRejected("audio_metadata_invalid") from exc
    return round(duration * 1000)
