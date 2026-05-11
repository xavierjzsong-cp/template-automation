from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    sync_playwright,
    Page,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
)

from src.adapters.base_adapter import BaseAdapter
from src.utils import ensure_dir, setup_logger

# --------------------------------------------------------------------------------------------------------------------------
# 目前这一版先只实现 datasheet_generator 页面：
# 打开页面 → 按顺序选择 hardcode 的 7 个字段 → 等待右侧 datasheet 内容加载出来
# --------------------------------------------------------------------------------------------------------------------------

class JfeAdapter(BaseAdapter):

    NA = "NA"

    DATASHEET_SELECTIONS = [
        ("Connection", "JFEBEAR"),
        ("Size", "3.500"),
        ("Weight", "9.2"),
        ("Grade", "L80-13CR"),
        ("Friction", "API Modified"),
        ("Coupling", "STD"),
        ("Bevel", "45° Standard"),
    ]

    FIELD_LABEL_ALIASES = {
        "Connection": ["Connection"],
        "Size": ["Size", "OD", "Outside Diameter"],
        "Weight": ["Weight"],
        "Grade": ["Grade"],
        "Friction": ["Friction", "Thread Compound", "Compound"],
        "Coupling": ["Coupling"],
        "Bevel": ["Bevel"],
    }

    def __init__(
        self,
        base_url: str,
        datasheet_url: str,
        blanking_url: str,
        logs_dir: Path,
        headless: bool = False,
        slow_mo: int = 300,
        timeout_ms: int = 10000,
        navigation_timeout_ms: int = 60000,
    ) -> None:
        self.base_url = base_url
        self.datasheet_url = datasheet_url
        self.blanking_url = blanking_url
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms

        ensure_dir(self.logs_dir)

        self.logger = setup_logger(self.logs_dir, "jfe_adapter_v2.0")

        self.playwright = sync_playwright().start()
        self.browser: Browser = self.playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )
        self.context: BrowserContext = self.browser.new_context()
        self.page: Page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.set_default_navigation_timeout(self.navigation_timeout_ms)

    def close(self) -> None:
        try:
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except Exception:
            pass

    def run(self, mapped_data: dict[str, Any]) -> dict[str, Any]:
        self.logger.info("Starting JFE extraction flow")
        self.logger.info("Mapped data: %s", mapped_data)

        self.open_datasheet_page()
        self._wait_for_datasheet_page_ready()

        self._select_datasheet_options()
        self._wait_for_datasheet_result_loaded()

        return self.extract_required_data(
            mapped_data=mapped_data,
        )

    # Page open
    def open_datasheet_page(self) -> None:
        self.logger.info(
            "Opening JFE connection datasheet page: %s",
            self.datasheet_url,
        )
        self._goto_page(self.datasheet_url)

    def open_blanking_page(self) -> None:
        self.logger.info(
            "Opening JFE blanking dimensions page: %s",
            self.blanking_url,
        )
        self._goto_page(self.blanking_url)

    def _goto_page(self, url: str) -> None:
        try:
            self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
        except PlaywrightTimeoutError:
            self.logger.warning(
                "Navigation timeout. Continue with page readiness check: %s",
                url,
            )

        try:
            self.page.wait_for_load_state("load", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass

    # ------------------------------------------------------------------
    # Page readiness checks
    # ------------------------------------------------------------------

    def _wait_for_datasheet_page_ready(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                const builder = document.querySelector("#datasheet_builder");
                if (!builder) return false;

                const selects = Array.from(builder.querySelectorAll("select"));
                if (selects.length < 2) return false;

                const connectionSelect = selects.find(select => {
                    const options = Array.from(select.options || []);
                    return options.some(o => (o.textContent || "").trim() === "JFEBEAR");
                });

                return Boolean(connectionSelect);
            }
            """,
            timeout=30000,
        )

        self._wait_for_loading_overlay_hidden()

    def _wait_for_blanking_page_ready(self) -> None:
        self.page.wait_for_timeout(1000)

    def _wait_for_loading_overlay_hidden(self) -> None:
        try:
            self.page.wait_for_function(
                """
                () => {
                    const overlay = document.querySelector(
                        "#datasheet_builder .loading-overlay"
                    );

                    if (!overlay) return true;

                    const style = window.getComputedStyle(overlay);

                    return style.display === "none"
                        || style.visibility === "hidden"
                        || !overlay.classList.contains("is-active");
                }
                """,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            pass

    def _wait_for_datasheet_result_loaded(self) -> None:
        self._wait_for_loading_overlay_hidden()

        self.page.wait_for_function(
            """
            () => {
                const page = document.querySelector("#datasheet_page");
                if (!page) return false;

                const contentColumns = Array.from(
                    page.querySelectorAll(".padding-xy-3 .columns.is-mobile > .column")
                ).filter(el => !el.classList.contains("sidebar"));

                const contentText = contentColumns
                    .map(el => el.innerText || "")
                    .join(" ")
                    .replace(/\\s+/g, " ")
                    .trim();

                const downloadButtonEnabled = Array.from(
                    document.querySelectorAll("button")
                ).some(button => {
                    const text = (button.innerText || "").trim();
                    return text.includes("Download") && !button.disabled;
                });

                return contentText.length > 30 || downloadButtonEnabled;
            }
            """,
            timeout=30000,
        )

    # ------------------------------------------------------------------
    # Datasheet selections
    # ------------------------------------------------------------------

    def _select_datasheet_options(self) -> None:
        for field_label, option_text in self.DATASHEET_SELECTIONS:
            self._select_datasheet_dropdown(
                field_label=field_label,
                option_text=option_text,
            )

    def _select_datasheet_dropdown(
        self,
        field_label: str,
        option_text: str,
    ) -> None:
        select = self._wait_for_select_with_placeholder(
            field_label=field_label,
            timeout_ms=30000,
        )

        matched_value = self._find_option_value_by_text(
            select=select,
            target_text=option_text,
        )

        if matched_value is None:
            available_options = self._get_select_option_texts(select)
            raise RuntimeError(
                f"JFE option not found. "
                f"field=[{field_label}], target=[{option_text}], "
                f"available_options={available_options}"
            )

        select.scroll_into_view_if_needed()
        select.select_option(value=matched_value)

        self.page.wait_for_timeout(1000)
        self._wait_for_loading_overlay_hidden()

        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

    def _wait_for_select_with_placeholder(
        self,
        field_label: str,
        timeout_ms: int = 30000,
    ):
        elapsed = 0
        interval = 500

        while elapsed < timeout_ms:
            select = self._get_select_by_placeholder(field_label)
            if select is not None:
                return select

            self.page.wait_for_timeout(interval)
            elapsed += interval

        raise RuntimeError(f"JFE select not found for field: {field_label}")

    def _get_select_by_placeholder(self, field_label: str):
        aliases = self.FIELD_LABEL_ALIASES.get(field_label, [field_label])
        normalized_aliases = {
            self._normalize_option_text(alias).upper()
            for alias in aliases
        }

        scope = self._get_left_panel_scope()
        selects = scope.locator("select")

        try:
            count = selects.count()
        except Exception:
            count = 0

        for i in range(count):
            select = selects.nth(i)

            try:
                if not select.is_visible(timeout=500):
                    continue
            except Exception:
                continue

            option_texts = self._get_select_option_texts(select)
            normalized_options = {
                self._normalize_option_text(text).upper()
                for text in option_texts
            }

            if normalized_aliases.intersection(normalized_options):
                return select

        return None

    def _get_left_panel_scope(self):
        candidates = [
            self.page.locator("#datasheet_builder .left_col").first,
            self.page.locator("#datasheet_builder").first,
            self.page.locator(".column.is-narrow.hide-for-print").first,
        ]

        for candidate in candidates:
            try:
                if candidate.is_visible(timeout=1000):
                    return candidate
            except Exception:
                continue

        raise RuntimeError("Could not find JFE left panel scope.")

    def _get_select_option_texts(self, select) -> list[str]:
        options = select.locator("option")
        texts: list[str] = []

        try:
            count = options.count()
        except Exception:
            return texts

        for i in range(count):
            try:
                raw_text = options.nth(i).text_content(timeout=500)
                text = self._normalize_option_text(raw_text)
                if text:
                    texts.append(text)
            except Exception:
                continue

        return texts

    def _find_option_value_by_text(
        self,
        select,
        target_text: str,
    ) -> str | None:
        options = select.locator("option")

        target_normalized = self._normalize_option_text(target_text)
        target_upper = target_normalized.upper()
        target_number = self._extract_first_number(target_normalized)

        best_value = None
        best_score = None

        try:
            count = options.count()
        except Exception:
            count = 0

        for i in range(count):
            try:
                option = options.nth(i)

                disabled = option.get_attribute("disabled")
                hidden = option.get_attribute("hidden")

                if disabled is not None or hidden is not None:
                    continue

                raw_text = option.text_content(timeout=500)
                option_text = self._normalize_option_text(raw_text)
                option_upper = option_text.upper()

                if not option_text:
                    continue

                score = self._score_option_match(
                    option_text=option_text,
                    option_upper=option_upper,
                    target_text=target_normalized,
                    target_upper=target_upper,
                    target_number=target_number,
                )

                if score is None:
                    continue

                value = option.get_attribute("value")
                if value is None:
                    continue

                if best_score is None or score > best_score:
                    best_score = score
                    best_value = value

            except Exception:
                continue

        return best_value

    def _score_option_match(
        self,
        option_text: str,
        option_upper: str,
        target_text: str,
        target_upper: str,
        target_number: float | None,
    ) -> int | None:
        if option_upper == target_upper:
            return 10000

        option_number = self._extract_first_number(option_text)

        if target_number is not None and option_number is not None:
            if option_number == target_number:
                return 9000 - len(option_text)

        compact_option = self._normalize_for_contains(option_upper)
        compact_target = self._normalize_for_contains(target_upper)

        if compact_target and compact_target in compact_option:
            return 7000 - len(option_text)

        if compact_option and compact_option in compact_target:
            return 6000 - len(option_text)

        return None

    # ------------------------------------------------------------------
    # Extraction entry
    # ------------------------------------------------------------------

    def extract_required_data(
        self,
        mapped_data: dict[str, Any],
    ) -> dict[str, Any]:
        right_text = self._get_datasheet_content_text()

        return {
            "status": "datasheet_selected",
            "source": "JFE",
            "datasheet_url": self.datasheet_url,
            "blanking_url": self.blanking_url,
            "mapped_data": mapped_data,
            "hardcoded_selections": dict(self.DATASHEET_SELECTIONS),
            "datasheet_content_preview": right_text[:500],
        }

    def _get_datasheet_content_text(self) -> str:
        try:
            page = self.page.locator("#datasheet_page").first
            text = page.inner_text(timeout=5000)
            return self._normalize_option_text(text)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _normalize_option_text(self, text: str | None) -> str:
        if not text:
            return ""

        text = text.replace("\u00a0", " ")
        text = text.replace("º", "°")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalize_for_contains(self, text: str) -> str:
        text = self._normalize_option_text(text)
        text = text.replace(" ", "")
        text = text.replace("-", "")
        text = text.replace("_", "")
        return text.upper()

    def _extract_first_number(self, text: str | None) -> float | None:
        if not text:
            return None

        match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None