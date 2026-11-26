import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless

from django.test import SimpleTestCase

from apps.profiles.media import MediaRejected, process_audio


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg runtime is required")
class ChatAudioLimitTests(SimpleTestCase):
    def test_chat_accepts_longer_notes_without_extending_profile_capsules(self):
        with TemporaryDirectory(prefix="anonymoke-chat-audio-") as folder:
            path = Path(folder) / "synthetic.m4a"
            subprocess.run(  # noqa: S603 - fixed synthetic test audio, no user-controlled arguments
                [
                    shutil.which("ffmpeg"),
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=20:sample_rate=48000",
                    "-c:a",
                    "aac",
                    str(path),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            source = path.read_bytes()
            voice = SimpleNamespace(disguise_voice=True)
            with self.assertRaises(MediaRejected):
                process_audio(voice, source)
            output, duration = process_audio(voice, source, max_duration_ms=60000)
            self.assertTrue(output)
            self.assertGreater(duration, 19000)
            self.assertLessEqual(duration, 20500)

    def test_voice_notes_over_one_minute_are_rejected(self):
        with TemporaryDirectory(prefix="anonymoke-chat-audio-") as folder:
            path = Path(folder) / "synthetic.m4a"
            subprocess.run(  # noqa: S603 - fixed synthetic test audio
                [
                    shutil.which("ffmpeg"),
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=62:sample_rate=48000",
                    "-c:a",
                    "aac",
                    str(path),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            with self.assertRaises(MediaRejected):
                process_audio(
                    SimpleNamespace(disguise_voice=True), path.read_bytes(), max_duration_ms=60000
                )
