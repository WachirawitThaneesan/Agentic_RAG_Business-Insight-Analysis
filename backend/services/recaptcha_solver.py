"""Audio reCAPTCHA solver for the Playwright scraping worker."""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Optional

import pydub
import requests
import speech_recognition as sr
from playwright.sync_api import Page


if os.name == "nt":
    if os.path.exists("ffmpeg.exe"):
        pydub.AudioSegment.converter = os.path.abspath("ffmpeg.exe")
        pydub.AudioSegment.ffprobe = os.path.abspath("ffprobe.exe")
    else:
        pydub.AudioSegment.converter = "ffmpeg"
        pydub.AudioSegment.ffprobe = "ffprobe"


class RecaptchaSolver:
    """Solve reCAPTCHA by clicking the circle first, then using audio."""

    TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"

    def __init__(self, page: Page) -> None:
        self.page = page
        self.recognizer = sr.Recognizer()

    def solve_captcha(self, max_retries: int = 3) -> bool:
        try:
            self.page.wait_for_selector('iframe[title="reCAPTCHA"]', state="attached", timeout=3000)
        except Exception:
            return True

        frame_main = self.page.frame_locator('iframe[title="reCAPTCHA"]')

        # First click the checkbox circle.
        try:
            checkbox = frame_main.locator(".recaptcha-checkbox-border")
            if checkbox.is_visible():
                checkbox.hover()
                time.sleep(random.uniform(0.3, 0.7))
                checkbox.click()
                time.sleep(1.0)
        except Exception:
            pass

        if self.is_solved():
            return True

        # If the circle alone is not enough, switch to the audio challenge.
        frame_challenge = self.page.frame_locator('iframe[src*="bframe"]')
        try:
            btn_audio = frame_challenge.locator("#recaptcha-audio-button")
            btn_audio.wait_for(state="visible", timeout=5000)
            btn_audio.click()
            time.sleep(1.5)
        except Exception:
            return False

        for _attempt in range(1, max_retries + 1):
            if self.is_detected(frame_challenge):
                return False

            try:
                audio_source = frame_challenge.locator("#audio-source")
                audio_source.wait_for(state="attached", timeout=5000)
                src = audio_source.get_attribute("src")
                if not src:
                    raise RuntimeError("No reCAPTCHA audio source found")

                text = self._audio_to_text(src)
                if not text:
                    raise RuntimeError("Could not transcribe reCAPTCHA audio")

                input_box = frame_challenge.locator("#audio-response")
                input_box.clear()
                for char in text.lower():
                    input_box.type(char, delay=random.randint(50, 200))

                time.sleep(0.5)
                frame_challenge.locator("#recaptcha-verify-button").click()
                time.sleep(2.0)

                if self.is_solved():
                    return True

                reload_btn = frame_challenge.locator("#recaptcha-reload-button")
                if reload_btn.is_visible():
                    reload_btn.click()
                    time.sleep(2.0)
            except Exception:
                try:
                    reload_btn = frame_challenge.locator("#recaptcha-reload-button")
                    if reload_btn.is_visible():
                        reload_btn.click()
                        time.sleep(2.0)
                except Exception:
                    pass

        return False

    def _audio_to_text(self, url: str) -> Optional[str]:
        temp_dir = Path(self.TEMP_DIR or ".")
        mp3_path = temp_dir / f"audio_{random.randint(1000, 9999)}.mp3"
        wav_path = temp_dir / f"audio_{random.randint(1000, 9999)}.wav"

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.google.com/",
            }
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return None

            mp3_path.write_bytes(response.content)
            sound = pydub.AudioSegment.from_mp3(str(mp3_path))
            sound.export(str(wav_path), format="wav")

            with sr.AudioFile(str(wav_path)) as source:
                audio_data = self.recognizer.record(source)
                return self.recognizer.recognize_google(audio_data)
        except Exception:
            return None
        finally:
            for path in (mp3_path, wav_path):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass

    def is_solved(self) -> bool:
        try:
            frame_main = self.page.frame_locator('iframe[title="reCAPTCHA"]')
            if frame_main.locator(".recaptcha-checkbox-checked").count() > 0:
                return True
            checkbox = frame_main.locator("#recaptcha-anchor")
            return checkbox.get_attribute("aria-checked") == "true"
        except Exception:
            return False

    def is_detected(self, frame_challenge) -> bool:
        try:
            if frame_challenge.locator("text=Try again later").is_visible():
                return True
            if frame_challenge.locator("text=Your computer or network may be sending automated queries").is_visible():
                return True
            return False
        except Exception:
            return False
