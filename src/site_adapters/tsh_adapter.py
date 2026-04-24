from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    sync_playwright,
    Page,
    Browser,
    BrowserContext,
)

from src.site_adapters.base_adapter import BaseAdapter
from src.utils import ensure_dir, setup_logger


class TshAdapter(BaseAdapter):
    def __init__(
        self,
        base_url: str,
        datasheet_url: str,
        blanking_url: str,
        logs_dir: Path,
        headless: bool = False,
        slow_mo: int = 300,
        timeout_ms: int = 10000,
    ) -> None:
        self.base_url = base_url
        self.datasheet_url = datasheet_url
        self.blanking_url = blanking_url
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms

        ensure_dir(self.logs_dir)

        self.logger = setup_logger(self.logs_dir, "tsh_adapter_v1.1")

        self.playwright = sync_playwright().start()
        self.browser: Browser = self.playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )
        self.context: BrowserContext = self.browser.new_context()
        self.page: Page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)

    def close(self) -> None:
        try:
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except Exception:
            pass

    def run(self, mapped_data: dict[str, Any]) -> dict[str, Any]:
        connection = mapped_data.get("connection") or {}

        od = connection.get("od")
        weight = connection.get("weight")
        grade = connection.get("grade")
        connection_name = connection.get("name")

        if not od or not weight or not grade or not connection_name:
            raise ValueError(
                "TSH mapped_data missing one of required fields: od, weight, grade, connection.name"
            )

        # Product Datasheet flow
        self.open_datasheet_page()

        self._select_od(od)
        self._select_weight(weight)
        self._select_grade(grade)
        self._select_connection(connection_name)

        self._wait_for_result_loaded()

        datasheet_result = self._extract_connection_data_performance()

        # Blanking Dimensions flow
        self.open_blanking_page()

        self._select_blanking_od(od)
        self._select_blanking_weight(weight)
        self._select_blanking_connection(connection_name)

        self._wait_for_blanking_result_loaded()

        return datasheet_result

    # Page open
    def open_datasheet_page(self) -> None:
        self.page.goto(self.datasheet_url, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    def open_blanking_page(self) -> None:
        self.page.goto(self.blanking_url, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    # Product Datasheet dropdowns
    def _select_od(self, od_value: str) -> None:
        options = self._get_dropdown_option_texts(0)
        selected = self._find_exact_option(options, od_value)
        if selected is None:
            raise RuntimeError(f"TSH OD option not found for value: {od_value}")

        self._set_dropdown_value_by_text(0, selected)

    def _select_weight(self, weight_value: str) -> None:
        options = self._get_dropdown_option_texts(1)
        selected = self._find_weight_option_datasheet(options, weight_value)
        if selected is None:
            raise RuntimeError(f"TSH weight option not found for value: {weight_value}")

        self._set_dropdown_value_by_text(1, selected)

    def _select_grade(self, grade_value: str) -> None:
        options = self._get_dropdown_option_texts(2)
        selected = self._find_exact_option(options, grade_value)
        if selected is None:
            raise RuntimeError(f"TSH grade option not found for value: {grade_value}")

        self._set_dropdown_value_by_text(2, selected)

    def _select_connection(self, connection_target: str) -> None:
        options = self._get_dropdown_option_texts(3)
        selected = self._find_best_connection_option(options, connection_target)
        if selected is None:
            raise RuntimeError(
                f"TSH connection option not found for target: {connection_target}. "
                f"Available options: {options}"
            )

        self._set_dropdown_value_by_text(3, selected)

    # Blanking Dimensions dropdowns
    def _select_blanking_od(self, od_value: str) -> None:
        options = self._get_dropdown_option_texts(0)
        selected = self._find_exact_option(options, od_value)
        if selected is None:
            raise RuntimeError(f"TSH blanking OD option not found for value: {od_value}")

        self._set_dropdown_value_by_text(0, selected)

    def _select_blanking_weight(self, weight_value: str) -> None:
        options = self._get_dropdown_option_texts(1)
        selected = self._find_weight_option_blanking(options, weight_value)
        if selected is None:
            raise RuntimeError(f"TSH blanking weight option not found for value: {weight_value}")

        self._set_dropdown_value_by_text(1, selected)

    def _select_blanking_connection(self, connection_target: str) -> None:
        options = self._get_dropdown_option_texts(2)
        selected = self._find_best_connection_option(options, connection_target)
        if selected is None:
            raise RuntimeError(
                f"TSH blanking connection option not found for target: {connection_target}. "
                f"Available options: {options}"
            )

        self._set_dropdown_value_by_text(2, selected)

    def _get_dropdown_models(self):
        return self.page.locator(".dropdown-select")

    def _get_dropdown_triggers(self):
        return self.page.locator("div.select-dropdown[data-component='dropdown']")

    def _get_dropdown_rendered_text(self, dropdown_index: int) -> str:
        triggers = self._get_dropdown_triggers()
        trigger_count = triggers.count()

        if trigger_count <= dropdown_index:
            raise RuntimeError(f"TSH dropdown trigger index {dropdown_index} not found")

        trigger = triggers.nth(dropdown_index)

        rendered = trigger.locator(".select2-selection__rendered").first
        if rendered.count() > 0:
            return rendered.inner_text(timeout=1000).strip()

        # fallback
        return trigger.inner_text(timeout=1000).strip()

    def _get_dropdown_option_texts(self, dropdown_index: int) -> list[str]:
        models = self._get_dropdown_models()
        count = models.count()

        if count <= dropdown_index:
            raise RuntimeError(
                f"TSH dropdown model index {dropdown_index} not found. Found count={count}"
            )

        model = models.nth(dropdown_index)
        options = model.locator("option.dropdown-option")

        texts: list[str] = []
        for i in range(options.count()):
            text = options.nth(i).inner_text(timeout=1000).strip()
            if text:
                texts.append(text)

        return texts

    def _set_dropdown_value_by_text(self, dropdown_index: int, option_text: str) -> None:
        models = self._get_dropdown_models()
        triggers = self._get_dropdown_triggers()

        model_count = models.count()
        trigger_count = triggers.count()

        if model_count <= dropdown_index:
            raise RuntimeError(f"TSH dropdown model index {dropdown_index} not found")
        if trigger_count <= dropdown_index:
            raise RuntimeError(f"TSH dropdown trigger index {dropdown_index} not found")

        model = models.nth(dropdown_index)
        trigger = triggers.nth(dropdown_index)

        # 先尝试点击 visible trigger，让页面聚焦到该下拉
        try:
            trigger.scroll_into_view_if_needed()
            trigger.click(force=True)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        handle = model.element_handle()
        if handle is None:
            raise RuntimeError(f"TSH dropdown model handle not found for index {dropdown_index}")

        selected = handle.evaluate(
            """
            (el, desiredText) => {
                const options = Array.from(el.querySelectorAll("option.dropdown-option"));
                const target = options.find(
                    o => (o.textContent || "").trim() === desiredText
                );
                if (!target) return false;

                options.forEach(o => o.removeAttribute("selected"));
                target.setAttribute("selected", "selected");

                if ("value" in el) {
                    el.value = target.value;
                }

                el.setAttribute("data-selected-value", target.value);

                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));

                if (window.jQuery) {
                    window.jQuery(el).trigger("change");
                }

                return true;
            }
            """,
            option_text,
        )

        if not selected:
            raise RuntimeError(
                f"TSH failed to set dropdown index {dropdown_index} to option [{option_text}]"
            )

        self.page.wait_for_timeout(1000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    # Option matchers
    def _find_exact_option(self, options: list[str], target: str) -> str | None:
        for option in options:
            if option.strip() == target.strip():
                return option
        return None

    def _find_weight_option_datasheet(self, options: list[str], target_weight: str) -> str | None:
        try:
            target_num = float(target_weight)
        except ValueError:
            target_num = None

        for option in options:
            option_text = option.strip()
            paren_match = re.search(r"\((.*?)\)", option_text)
            if not paren_match:
                continue

            raw_tokens = [t.strip() for t in paren_match.group(1).split(",")]
            for token in raw_tokens:
                try:
                    if target_num is not None and float(token) == target_num:
                        return option_text
                except ValueError:
                    continue

        for option in options:
            if target_weight.strip() in option:
                return option

        return None

    def _find_weight_option_blanking(self, options: list[str], target_weight: str) -> str | None:
        try:
            target_num = float(target_weight)
        except ValueError:
            target_num = None

        for option in options:
            option_text = option.strip()
            paren_match = re.search(r"\((.*?)\)", option_text)
            if not paren_match:
                continue

            token = paren_match.group(1).strip()
            try:
                if target_num is not None and float(token) == target_num:
                    return option_text
            except ValueError:
                continue

        for option in options:
            if target_weight.strip() in option:
                return option

        return None

    def _find_best_connection_option(self, options: list[str], target: str) -> str | None:
        normalized_target = self._normalize_connection_text(target)
        target_tokens = self._tokenize_connection(normalized_target)
        target_numbers = self._extract_number_tokens(normalized_target)

        best_option = None
        best_score = None

        for option in options:
            normalized_option = self._normalize_connection_text(option)
            option_tokens = self._tokenize_connection(normalized_option)
            option_numbers = self._extract_number_tokens(normalized_option)

            score = self._score_connection_match(
                normalized_target=normalized_target,
                normalized_option=normalized_option,
                target_tokens=target_tokens,
                option_tokens=option_tokens,
                target_numbers=target_numbers,
                option_numbers=option_numbers,
            )

            if score is None:
                continue

            if best_score is None or score > best_score:
                best_score = score
                best_option = option

        return best_option

    def _normalize_connection_text(self, text: str | None) -> str:
        if not text:
            return ""

        normalized = text.upper().strip()

        normalized = re.sub(r"^\s*TSH\s+", "", normalized)

        normalized = normalized.replace("®", " ")
        normalized = normalized.replace("™", " ")

        normalized = re.sub(r"[-_/]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _tokenize_connection(self, normalized_text: str) -> list[str]:
        return re.findall(r"[A-Z0-9.]+", normalized_text)

    def _extract_number_tokens(self, normalized_text: str) -> list[str]:
        return re.findall(r"\d+(?:\.\d+)?", normalized_text)

    def _score_connection_match(
        self,
        normalized_target: str,
        normalized_option: str,
        target_tokens: list[str],
        option_tokens: list[str],
        target_numbers: list[str],
        option_numbers: list[str],
    ) -> int | None:
        option_token_set = set(option_tokens)
        target_token_set = set(target_tokens)

        if normalized_option == normalized_target:
            return 100000 - len(option_tokens)

        if not target_token_set.issubset(option_token_set):
            return None

        score = 0

        if target_numbers:
            if option_numbers == target_numbers:
                score += 50000
            elif set(target_numbers).issubset(set(option_numbers)):
                score += 30000
            else:
                return None

        score += 10000

        if normalized_option.startswith(normalized_target):
            score += 3000

        extra_tokens = len(option_tokens) - len(target_tokens)
        score -= extra_tokens * 100
        score -= len(normalized_option)

        return score

    def _wait_for_result_loaded(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                const txt = document.body.innerText || "";
                return txt.includes("Connection Data")
                    && txt.includes("Performance")
                    && txt.includes("Joint Yield Strength")
                    && txt.includes("Compression Strength");
            }
            """,
            timeout=15000,
        )

    def _extract_connection_data_performance(self) -> dict[str, Any]:
        body_text = self.page.locator("body").inner_text(timeout=5000)
        normalized = self._normalize_text(body_text)

        connection_section = self._extract_section(
            text=normalized,
            start_label="Connection Data",
            end_candidates=["Make-Up Torques", "Operation Limit Torques"],
        )

        performance_section = self._extract_section(
            text=connection_section,
            start_label="Performance",
            end_candidates=["Make-Up Torques", "Operation Limit Torques"],
        )

        return {
            "tensile": self._extract_first_number_after_label(
                performance_section,
                "Joint Yield Strength",
            ),
            "compression": self._extract_first_number_after_label(
                performance_section,
                "Compression Strength",
            ),
            "burst": self._extract_first_number_after_label(
                performance_section,
                "Internal Pressure Capacity",
            ),
            "collapse": self._extract_first_number_after_label(
                performance_section,
                "External Pressure Capacity",
            ),
        }

    def _wait_for_blanking_result_loaded(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                const txt = document.body.innerText || "";
                return txt.includes("Blanking Dimensions")
                    && !txt.includes("Choose pipe size, weight and connection to view blanking dimensions data");
            }
            """,
            timeout=15000,
        )

    def _extract_section(
        self,
        text: str,
        start_label: str,
        end_candidates: list[str],
    ) -> str:
        start_idx = text.find(start_label)
        if start_idx == -1:
            return text

        end_idx = len(text)
        for candidate in end_candidates:
            idx = text.find(candidate, start_idx + len(start_label))
            if idx != -1 and idx < end_idx:
                end_idx = idx

        return text[start_idx:end_idx].strip()

    def _extract_first_number_after_label(self, text: str, label: str) -> str | None:
        pattern = rf"{re.escape(label)}\s+([+\-]?\d+(?:,\d{{3}})*(?:\.\d+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()