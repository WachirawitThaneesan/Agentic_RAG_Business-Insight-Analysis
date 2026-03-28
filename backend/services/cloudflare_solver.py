"""Cloudflare challenge helpers for the Playwright scraping worker."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudflareSolveResult:
    solved: bool
    method: str
    token: Optional[str] = None


class CloudflareSolver:
    """Solve Cloudflare challenges using an existing sync Playwright page."""

    def __init__(self, page: Page, sleep_seconds: float = 1.5, retries: int = 20) -> None:
        self.page = page
        self.sleep_seconds = max(sleep_seconds, 0.0)
        self.retries = max(retries, 1)

    def solve(self) -> CloudflareSolveResult:
        if not self._has_challenge():
            return CloudflareSolveResult(solved=False, method="not_detected")

        logger.info("Cloudflare challenge detected; attempting solve")
        for _attempt in range(self.retries):
            clicked = self._find_and_click_challenge_frame()
            if clicked:
                self.page.wait_for_timeout(int(self.sleep_seconds * 1000))

            clearance = self._get_cf_clearance_cookie()
            if clearance:
                return CloudflareSolveResult(solved=True, method="cf_clearance", token=clearance)

            token = self._get_turnstile_token()
            if token:
                return CloudflareSolveResult(solved=True, method="turnstile", token=token)

            self.page.wait_for_timeout(1000)

        return CloudflareSolveResult(solved=False, method="failed")

    def _has_challenge(self) -> bool:
        if self.page.locator('input[name="cf-turnstile-response"]').count() > 0:
            return True
        return any(frame.url.startswith("https://challenges.cloudflare.com") for frame in self.page.frames)

    def _find_and_click_challenge_frame(self) -> bool:
        for frame in self.page.frames:
            if not frame.url.startswith("https://challenges.cloudflare.com"):
                continue

            try:
                frame_element = frame.frame_element()
                bounding_box = frame_element.bounding_box()
                if not bounding_box:
                    continue

                checkbox_x = bounding_box["x"] + bounding_box["width"] / 9
                checkbox_y = bounding_box["y"] + bounding_box["height"] / 2

                target_x = checkbox_x + random.uniform(-5, 5)
                target_y = checkbox_y + random.uniform(-5, 5)
                self.page.mouse.move(target_x, target_y, steps=random.randint(10, 25))
                time.sleep(random.uniform(0.1, 0.3))
                self.page.mouse.down()
                time.sleep(random.uniform(0.05, 0.15))
                self.page.mouse.up()
                return True
            except Exception as exc:
                logger.debug("Cloudflare click failed: %s", exc)
                continue

        return False

    def _get_cf_clearance_cookie(self) -> Optional[str]:
        try:
            cookies = self.page.context.cookies()
        except Exception:
            return None

        for cookie in cookies:
            if cookie.get("name") == "cf_clearance":
                return str(cookie.get("value") or "")
        return None

    def _get_turnstile_token(self) -> Optional[str]:
        try:
            token_inputs = self.page.locator('input[name="cf-turnstile-response"]')
            for index in range(token_inputs.count()):
                token = token_inputs.nth(index).get_attribute("value")
                if token and len(token) > 10:
                    return token
        except Exception:
            return None
        return None
