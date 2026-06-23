from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src.utils import ensure_dir, setup_logger

from .base_adapter import BaseAdapter


class PlaywrightAdapterTestBase(BaseAdapter):
    def __init__(
        self,
        logs_dir: Path,
        logger_name: str,
        headless: bool,
        slow_mo: int,
        timeout_ms: int,
        navigation_timeout_ms: int | None = None,
    ) -> None:
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms

        ensure_dir(self.logs_dir)
        self.logger = setup_logger(self.logs_dir, logger_name)

        self.playwright = sync_playwright().start()
        self.browser: Browser = self.playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )
        self.context: BrowserContext = self.browser.new_context()
        self.page: Page = self.context.new_page()
        self._configure_page_timeouts(self.page)

    def _configure_page_timeouts(self, page: Page) -> None:
        page.set_default_timeout(self.timeout_ms)
        if self.navigation_timeout_ms is not None:
            page.set_default_navigation_timeout(self.navigation_timeout_ms)

    def close(self) -> None:
        for resource in (
            getattr(self, "context", None),
            getattr(self, "browser", None),
            getattr(self, "playwright", None),
        ):
            try:
                if resource is not None:
                    resource.close() if resource is not self.playwright else resource.stop()
            except Exception:
                pass

    def safe_goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int | None = None,
        wait_for_load: bool = True,
        wait_for_networkidle: bool = True,
    ) -> None:
        try:
            self.page.goto(
                url,
                wait_until=wait_until,
                timeout=timeout or self.navigation_timeout_ms,
            )
        except PlaywrightTimeoutError:
            self.logger.warning(
                "Navigation timeout. Continue with page readiness check: %s",
                url,
            )

        if wait_for_load:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except PlaywrightTimeoutError:
                pass

        if wait_for_networkidle:
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass


def normalize_text(text: Any) -> str:
    value = str(text or "")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_first_number(text: Any) -> str | None:
    value = normalize_text(text)
    match = re.search(r"[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)", value)
    if not match:
        return None
    return match.group(0)


def extract_section(text: str, start_label: str, end_candidates: list[str]) -> str:
    start_idx = text.find(start_label)
    if start_idx == -1:
        return text

    end_idx = len(text)
    for candidate in end_candidates:
        idx = text.find(candidate, start_idx + len(start_label))
        if idx != -1 and idx < end_idx:
            end_idx = idx

    return text[start_idx:end_idx].strip()
