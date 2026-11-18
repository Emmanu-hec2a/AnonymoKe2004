import os
import shutil
import subprocess
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import override_settings
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

if not settings.configured and not os.getenv("DJANGO_SETTINGS_MODULE"):
    settings.configure(SECRET_KEY="unit-tests", USE_TZ=True)

from .media import MediaRejected, _audio_duration_ms, process_audio, process_avatar  # noqa: E402
from .storage import MediaPayloadTooLarge, R2MediaStore  # noqa: E402


class AvatarPrivacyTests(TestCase):
    def setUp(self):
        self.enterContext(
            override_settings(MEDIA_AVATAR_MAX_BYTES=10485760, MEDIA_REQUIRE_EXACTLY_ONE_FACE=False)
        )

    def photo(self):
        photo = Image.new("RGB", (400, 300), "black")
        ImageDraw.Draw(photo).rectangle((200, 0, 400, 300), fill="white")
        exif = Image.Exif()
        exif[270] = "Private identifying metadata"
        output = BytesIO()
        photo.save(output, format="JPEG", exif=exif)
        return output.getvalue()

    def test_private_original_and_public_blur_are_distinct_and_strip_metadata(self):
        original, blurred = process_avatar(SimpleNamespace(), self.photo())
        source = Image.open(BytesIO(original))
        preview = Image.open(BytesIO(blurred))
        self.assertEqual(source.size, (400, 300))
        self.assertEqual(preview.size, (512, 512))
        self.assertFalse(source.getexif())
        self.assertFalse(preview.getexif())
        self.assertLess(ImageStat.Stat(preview).stddev[0], ImageStat.Stat(source).stddev[0] * 0.95)

    def test_softer_preview_retains_more_outline_than_the_previous_blur(self):
        original, current = process_avatar(SimpleNamespace(), self.photo())
        image = Image.open(BytesIO(original))
        legacy = ImageOps.fit(image, (24, 24), method=Image.Resampling.LANCZOS)
        legacy = legacy.filter(ImageFilter.GaussianBlur(radius=8))
        self.assertGreater(
            ImageStat.Stat(Image.open(BytesIO(current))).stddev[0],
            ImageStat.Stat(legacy).stddev[0] * 1.5,
        )

    def test_softer_preview_still_suppresses_fine_identifying_detail(self):
        image = Image.new("RGB", (400, 400), "black")
        draw = ImageDraw.Draw(image)
        for x in range(0, 400, 2):
            draw.line((x, 0, x, 399), fill="white")
        payload = BytesIO()
        image.save(payload, format="PNG")
        original, preview = process_avatar(SimpleNamespace(), payload.getvalue())
        self.assertLess(
            ImageStat.Stat(Image.open(BytesIO(preview))).stddev[0],
            ImageStat.Stat(Image.open(BytesIO(original))).stddev[0] * 0.15,
        )

    def test_corrupt_image_is_rejected(self):
        with self.assertRaisesRegex(MediaRejected, "avatar_invalid"):
            process_avatar(SimpleNamespace(), b"not-an-image")

    @override_settings(MEDIA_AVATAR_MAX_BYTES=100)
    def test_oversized_upload_is_rejected_before_decoding(self):
        with self.assertRaisesRegex(MediaRejected, "avatar_too_large"):
            process_avatar(SimpleNamespace(), b"x" * 101)

    @override_settings(MEDIA_REQUIRE_EXACTLY_ONE_FACE=True)
    def test_face_gate_rejects_a_non_face_image(self):
        with self.assertRaisesRegex(MediaRejected, "exactly_one_face_required"):
            process_avatar(SimpleNamespace(), self.photo())

    def test_small_photos_are_rejected(self):
        payload = BytesIO()
        Image.new("RGB", (100, 200)).save(payload, format="PNG")
        with self.assertRaisesRegex(MediaRejected, "avatar_dimensions_invalid"):
            process_avatar(SimpleNamespace(), payload.getvalue())

    def test_oversized_dimensions_are_rejected_before_pixel_decode(self):
        with patch("apps.profiles.media.Image.open") as opened:
            source = opened.return_value.__enter__.return_value
            source.format, source.size = "JPEG", (8001, 200)
            with patch("apps.profiles.media.ImageOps.exif_transpose") as decode:
                with self.assertRaisesRegex(MediaRejected, "avatar_dimensions_invalid"):
                    process_avatar(SimpleNamespace(), b"header")
                decode.assert_not_called()

    def test_animated_photos_are_rejected(self):
        payload = BytesIO()
        Image.new("RGB", (200, 200), "red").save(
            payload,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (200, 200), "blue")],
            duration=100,
            loop=0,
        )
        with self.assertRaisesRegex(MediaRejected, "avatar_still_photo_required"):
            process_avatar(SimpleNamespace(), payload.getvalue())

    def test_unsupported_image_formats_are_rejected(self):
        payload = BytesIO()
        Image.new("RGB", (200, 200)).save(payload, format="GIF")
        with self.assertRaisesRegex(MediaRejected, "avatar_format_invalid"):
            process_avatar(SimpleNamespace(), payload.getvalue())

    def test_orientation_is_applied_before_metadata_is_removed(self):
        payload = BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (400, 300)).save(payload, format="JPEG", exif=exif)
        original, _ = process_avatar(SimpleNamespace(), payload.getvalue())
        normalized = Image.open(BytesIO(original))
        self.assertEqual(normalized.size, (300, 400))
        self.assertFalse(normalized.getexif())

    def test_large_originals_are_reduced_without_upscaling_small_photos(self):
        payload = BytesIO()
        Image.new("RGB", (2500, 500)).save(payload, format="JPEG")
        original, _ = process_avatar(SimpleNamespace(), payload.getvalue())
        normalized = Image.open(BytesIO(original))
        self.assertEqual(normalized.width, 2048)
        self.assertAlmostEqual(normalized.width / normalized.height, 5, delta=0.02)

    @override_settings(MEDIA_REQUIRE_EXACTLY_ONE_FACE=True)
    @patch("cv2.CascadeClassifier")
    def test_group_photos_are_rejected(self, cascade):
        cascade.return_value.empty.return_value = False
        cascade.return_value.detectMultiScale.return_value = [(1, 1, 50, 50), (80, 1, 50, 50)]
        with self.assertRaisesRegex(MediaRejected, "exactly_one_face_required"):
            process_avatar(SimpleNamespace(), self.photo())


class MediaDownloadBoundsTests(TestCase):
    def store(self, payload):
        store = R2MediaStore.__new__(R2MediaStore)
        store.private_bucket = "private"
        store.client = Mock()
        body = BytesIO(payload)
        store.client.get_object.return_value = {"Body": body}
        return store, body

    def test_oversized_objects_are_bounded_even_if_replaced_after_upload_validation(self):
        store, body = self.store(b"too large")
        with self.assertRaisesRegex(MediaPayloadTooLarge, "media_size_invalid"):
            store.download("incoming/photo", max_bytes=3)
        self.assertTrue(body.closed)

    def test_valid_download_closes_the_remote_stream(self):
        store, body = self.store(b"photo")
        self.assertEqual(store.download("incoming/photo", max_bytes=5), b"photo")
        self.assertTrue(body.closed)


class AudioPrivacyTests(TestCase):
    def setUp(self):
        self.enterContext(
            override_settings(MEDIA_AUDIO_MAX_BYTES=5242880, MEDIA_AUDIO_MAX_DURATION_MS=15500)
        )

    def transcode(self, command, **kwargs):
        from pathlib import Path

        Path(command[-1]).write_bytes(b"processed AAC")
        self.command = command
        return SimpleNamespace(returncode=0)

    @patch("apps.profiles.media._audio_duration_ms", return_value=12000)
    def test_disguise_transcodes_only_audio_and_strips_identifying_metadata(self, probe):
        with patch("apps.profiles.media.subprocess.run", side_effect=self.transcode):
            payload, duration = process_audio(SimpleNamespace(disguise_voice=True), b"input audio")
        self.assertEqual(payload, b"processed AAC")
        self.assertEqual(duration, 12000)
        self.assertIn("-af", self.command)
        self.assertIn("asetrate=53760", self.command[self.command.index("-af") + 1])
        self.assertEqual(self.command[self.command.index("-map") + 1], "0:a:0")
        for option in ["-map_metadata", "-map_metadata:s:a", "-map_chapters"]:
            self.assertEqual(self.command[self.command.index(option) + 1], "-1")
        self.assertEqual(self.command[self.command.index("-protocol_whitelist") + 1], "file")
        self.assertEqual(self.command[self.command.index("-format_whitelist") + 1], "mov,mp3,wav")

    @patch("apps.profiles.media._audio_duration_ms", return_value=12000)
    def test_disguise_opt_out_keeps_pitch_unchanged_but_still_sanitizes_audio(self, probe):
        with patch("apps.profiles.media.subprocess.run", side_effect=self.transcode):
            process_audio(SimpleNamespace(disguise_voice=False), b"input audio")
        self.assertNotIn("-af", self.command)
        self.assertIn("-map_metadata", self.command)

    @patch("apps.profiles.media._audio_duration_ms", return_value=15300)
    def test_encoder_padding_is_tolerated_but_shared_capsule_is_limited_to_fifteen_seconds(
        self, probe
    ):
        with patch("apps.profiles.media.subprocess.run", side_effect=self.transcode):
            _, duration = process_audio(SimpleNamespace(disguise_voice=True), b"input audio")
        self.assertEqual(duration, 15000)
        self.assertEqual(self.command[self.command.index("-t") + 1], "15.0")

    def test_invalid_or_long_recordings_are_rejected_before_transcoding(self):
        for duration in [0, -1, 15501]:
            with self.subTest(duration=duration):
                with patch("apps.profiles.media._audio_duration_ms", return_value=duration):
                    with patch("apps.profiles.media.subprocess.run") as transcode:
                        with self.assertRaisesRegex(MediaRejected, "audio_duration_invalid"):
                            process_audio(SimpleNamespace(disguise_voice=True), b"input audio")
                        transcode.assert_not_called()

    @override_settings(MEDIA_AUDIO_MAX_BYTES=2)
    def test_oversized_recordings_are_rejected_without_invoking_ffprobe(self):
        with patch("apps.profiles.media._audio_duration_ms") as probe:
            with self.assertRaisesRegex(MediaRejected, "audio_too_large"):
                process_audio(SimpleNamespace(disguise_voice=True), b"big")
            probe.assert_not_called()

    def test_invalid_probe_durations_are_rejected_consistently(self):
        from pathlib import Path

        for value in ['"NaN"', '"Infinity"', '"-1"', '"0"', "null", "{}", '"not-a-number"']:
            with self.subTest(value=value):
                result = SimpleNamespace(stdout='{"format":{"duration":' + value + "}}")
                with patch("apps.profiles.media.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(MediaRejected, "audio_metadata_invalid"):
                        _audio_duration_ms(Path("source.m4a"))

    @patch("apps.profiles.media._audio_duration_ms", return_value=1000)
    def test_failed_decoder_is_not_reported_as_a_saved_capsule(self, probe):
        with patch(
            "apps.profiles.media.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            with self.assertRaisesRegex(MediaRejected, "audio_processing_unavailable"):
                process_audio(SimpleNamespace(disguise_voice=True), b"input audio")


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg runtime is required")
class RealAudioProcessingTests(TestCase):
    def test_audio_disguise_changes_pitch_and_removes_source_metadata(self):
        self.check_audio(disguise=True, expected_pitch=492.8)

    def test_plain_audio_retains_pitch_and_removes_source_metadata(self):
        self.check_audio(disguise=False, expected_pitch=440)

    def check_audio(self, *, disguise, expected_pitch):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        import numpy as np

        with override_settings(MEDIA_AUDIO_MAX_BYTES=5242880, MEDIA_AUDIO_MAX_DURATION_MS=15500):
            with TemporaryDirectory(prefix="anonymoke-audio-test-") as directory:
                source = Path(directory) / "input.m4a"
                processed = Path(directory) / "output.m4a"
                subprocess.run(  # noqa: S603 - fixed fixture, no user arguments
                    [
                        shutil.which("ffmpeg"),
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:duration=1:sample_rate=48000",
                        "-metadata",
                        "title=Private identifying alias",
                        "-c:a",
                        "aac",
                        str(source),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=20,
                )
                payload, duration = process_audio(
                    SimpleNamespace(disguise_voice=disguise), source.read_bytes()
                )
                processed.write_bytes(payload)
                self.assertLessEqual(abs(duration - 1000), 100)
                metadata = subprocess.run(  # noqa: S603 - fixed fixture paths
                    [
                        shutil.which("ffprobe"),
                        "-v",
                        "error",
                        "-show_entries",
                        "format_tags=title",
                        "-of",
                        "json",
                        str(processed),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertNotIn(
                    "title", json.loads(metadata.stdout).get("format", {}).get("tags", {})
                )
                pcm = subprocess.run(  # noqa: S603 - fixed fixture paths
                    [
                        shutil.which("ffmpeg"),
                        "-v",
                        "error",
                        "-i",
                        str(processed),
                        "-f",
                        "s16le",
                        "-ac",
                        "1",
                        "-ar",
                        "48000",
                        "pipe:1",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=20,
                ).stdout
                samples = np.frombuffer(pcm, dtype="<i2")[9600:-9600].astype(float)
                spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
                pitch = np.fft.rfftfreq(len(samples), d=1 / 48000)[np.argmax(spectrum)]
                self.assertLess(abs(pitch - expected_pitch), 6)
