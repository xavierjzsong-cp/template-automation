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
        navigation_timeout_ms: int = 60000,
    ) -> None:
        self.base_url = base_url
        self.datasheet_url = datasheet_url
        self.blanking_url = blanking_url
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms

        ensure_dir(self.logs_dir)

        self.logger = setup_logger(self.logs_dir, "tsh_adapter_v1.5")

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
        connection = mapped_data.get("connection") or {}

        od = connection.get("od")
        weight = connection.get("weight")
        grade = connection.get("grade")
        connection_name = connection.get("name")
        connection_type = (connection.get("type") or "").upper()

        drift_extraction = bool(mapped_data.get("drift_extraction"))

        if not od or not weight or not grade or not connection_name:
            raise ValueError(
                "TSH mapped_data missing one of required fields: od, weight, grade, connection.name"
            )

        if connection_type not in {"BOX", "PIN"}:
            raise ValueError(f"TSH mapped_data has unsupported connection.type: {connection_type}")

        # Product Datasheet flow
        self.open_datasheet_page()

        self._select_od(od)
        self._select_weight(weight)
        self._select_grade(grade)
        self._select_connection(connection_name)

        self._wait_for_connection_loaded()

        datasheet_result = self._extract_connection_performance()

        # Blanking Dimensions flow
        self.open_blanking_page()

        self._select_blanking_od(od)
        self._select_blanking_weight(weight)
        self._select_blanking_connection(connection_name)

        self._wait_for_blanking_dimensions_loaded()

        blanking_result = self._extract_blanking_dimensions(connection_type)

        drift_data: dict[str, Any] = {}
        if drift_extraction:
            drift_data = {
                "drift": self._extract_selected_product_drift()
            }

        return {
            **datasheet_result,
            **blanking_result,
            **drift_data,
        }

    def open_datasheet_page(self) -> None:
        self._goto_page(self.datasheet_url)
        self._wait_for_dropdowns_ready(expected_count=4)

    def open_blanking_page(self) -> None:
        self._goto_page(self.blanking_url)
        self._wait_for_dropdowns_ready(expected_count=3)

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

    def _wait_for_dropdowns_ready(self, expected_count: int) -> None:
        self.page.wait_for_function(
            """
            (expectedCount) => {
                const scope = document.querySelector(
                    "div.select-search div.drop-downs-container"
                );

                if (!scope) {
                    return false;
                }

                const roots = Array.from(
                    scope.querySelectorAll("div.select-dropdown[data-component='dropdown']")
                ).filter(root => root.querySelectorAll("option.dropdown-option").length > 0);

                if (roots.length < expectedCount) {
                    return false;
                }

                return roots
                    .slice(0, expectedCount)
                    .every(root => root.querySelectorAll("option.dropdown-option").length > 1);
            }
            """,
            arg=expected_count,
            timeout=20000,
        )

    def _select_od(self, od_value: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=0,
            search_text=od_value,
            match_mode="exact_or_numeric",
            target_value=od_value,
        )

    def _select_weight(self, weight_value: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=1,
            search_text=weight_value,
            match_mode="weight_datasheet",
            target_value=weight_value,
        )

    def _select_grade(self, grade_value: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=2,
            search_text=grade_value,
            match_mode="contains",
            target_value=grade_value,
        )

    def _select_connection(self, connection_target: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=3,
            search_text=connection_target,
            match_mode="connection",
            target_value=connection_target,
        )

    def _select_blanking_od(self, od_value: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=0,
            search_text=od_value,
            match_mode="exact_or_numeric",
            target_value=od_value,
        )

    def _select_blanking_weight(self, weight_value: str) -> None:
        search_text = self._strip_trailing_zero_for_search(weight_value)

        self._select_dropdown_by_search(
            dropdown_index=1,
            search_text=search_text,
            match_mode="weight_blanking",
            target_value=weight_value,
        )

    def _select_blanking_connection(self, connection_target: str) -> None:
        self._select_dropdown_by_search(
            dropdown_index=2,
            search_text=connection_target,
            match_mode="connection",
            target_value=connection_target,
        )

    def _select_dropdown_by_search(
        self,
        dropdown_index: int,
        search_text: str,
        match_mode: str,
        target_value: str | None = None,
    ) -> None:
        root = self._get_dropdown_root(dropdown_index)

        self._open_select2_dropdown(root)

        search_input = self._get_visible_select2_search_input()
        search_input.fill(search_text)
        self.page.wait_for_timeout(700)

        option = self._find_visible_select2_option(
            target_value=target_value or search_text,
            match_mode=match_mode,
        )

        if option is None:
            visible_options = self._get_visible_select2_option_texts()
            hidden_options = self._get_dropdown_option_texts(dropdown_index)
            raise RuntimeError(
                f"Could not find TSH dropdown option. "
                f"dropdown_index={dropdown_index}, search_text=[{search_text}], "
                f"target_value=[{target_value}], match_mode=[{match_mode}], "
                f"visible_options={visible_options}, hidden_options={hidden_options}"
            )

        option.scroll_into_view_if_needed()
        option.click(force=True)

        self.page.wait_for_timeout(1200)

        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    def _open_select2_dropdown(self, root) -> None:
        trigger_candidates = [
            root.locator(".select2-container").first,
            root.locator(".select2-selection").first,
            root.locator(".select2-selection__rendered").first,
            root.locator(".dropdownicon").first,
            root,
        ]

        opened = False

        for trigger in trigger_candidates:
            try:
                if trigger.is_visible(timeout=1000):
                    trigger.scroll_into_view_if_needed()
                    trigger.click(force=True)
                    self.page.wait_for_timeout(500)
                    opened = True
                    break
            except Exception:
                continue

        if not opened:
            raise RuntimeError("Could not open TSH Select2 dropdown.")

        try:
            self.page.locator(".select2-container--open").first.wait_for(
                state="visible",
                timeout=5000,
            )
        except Exception as exc:
            raise RuntimeError("TSH Select2 dropdown did not enter open state.") from exc

    def _get_visible_select2_search_input(self):
        candidates = [
            self.page.locator(".select2-container--open input.select2-search__field").first,
            self.page.locator(".select2-container--open input[role='searchbox']").first,
            self.page.locator("input.select2-search__field").first,
            self.page.locator("input[role='searchbox']").first,
            self.page.locator(".select2-dropdown input").first,
        ]

        for candidate in candidates:
            try:
                if candidate.is_visible(timeout=3000):
                    return candidate
            except Exception:
                continue

        raise RuntimeError("Could not locate visible Select2 search input.")

    def _find_visible_select2_option(self, target_value: str, match_mode: str):
        options = self.page.locator(
            ".select2-container--open .select2-results__option[role='option'], "
            ".select2-results__option[role='option'], "
            "li.select2-results__option, "
            "[role='option']"
        )

        best_option = None
        best_score = None

        try:
            count = options.count()
        except Exception:
            count = 0

        for i in range(count):
            try:
                option = options.nth(i)

                if not option.is_visible(timeout=500):
                    continue

                aria_disabled = option.get_attribute("aria-disabled")
                if aria_disabled == "true":
                    continue

                raw_text = option.text_content(timeout=1000)
                option_text = (raw_text or "").strip()

                if not option_text:
                    continue

                score = self._score_visible_option(
                    option_text=option_text,
                    target_value=target_value,
                    match_mode=match_mode,
                )

                if score is None:
                    continue

                if best_score is None or score > best_score:
                    best_score = score
                    best_option = option

            except Exception:
                continue

        return best_option

    def _get_visible_select2_option_texts(self) -> list[str]:
        options = self.page.locator(
            ".select2-container--open .select2-results__option[role='option'], "
            ".select2-results__option[role='option'], "
            "li.select2-results__option, "
            "[role='option']"
        )

        texts: list[str] = []

        try:
            count = options.count()
        except Exception:
            return texts

        for i in range(count):
            try:
                option = options.nth(i)
                if option.is_visible(timeout=300):
                    text = (option.text_content(timeout=500) or "").strip()
                    if text:
                        texts.append(text)
            except Exception:
                continue

        return texts

    def _get_dropdown_roots(self):
        return self.page.locator(
            "div.select-search div.drop-downs-container "
            "div.select-dropdown[data-component='dropdown']"
        ).filter(
            has=self.page.locator("option.dropdown-option")
        )

    def _get_dropdown_root(self, dropdown_index: int):
        roots = self._get_dropdown_roots()
        count = roots.count()

        if count <= dropdown_index:
            raise RuntimeError(
                f"TSH product dropdown root index {dropdown_index} not found. Found count={count}"
            )

        return roots.nth(dropdown_index)

    def _get_dropdown_option_texts(self, dropdown_index: int) -> list[str]:
        root = self._get_dropdown_root(dropdown_index)
        options = root.locator("option.dropdown-option")

        texts: list[str] = []
        option_count = options.count()

        for i in range(option_count):
            raw_text = options.nth(i).text_content(timeout=1000)
            text = (raw_text or "").strip()
            if text:
                texts.append(text)

        return texts

    def _score_visible_option(
        self,
        option_text: str,
        target_value: str,
        match_mode: str,
    ) -> int | None:
        if match_mode == "exact_or_numeric":
            return self._score_exact_or_numeric_option(option_text, target_value)

        if match_mode == "contains":
            return self._score_contains_option(option_text, target_value)

        if match_mode == "weight_datasheet":
            return self._score_weight_option_datasheet(option_text, target_value)

        if match_mode == "weight_blanking":
            return self._score_weight_option_blanking(option_text, target_value)

        if match_mode == "connection":
            return self._score_connection_option(option_text, target_value)

        return self._score_contains_option(option_text, target_value)

    def _score_exact_or_numeric_option(self, option_text: str, target_value: str) -> int | None:
        option_clean = self._normalize_dropdown_option_text(option_text)
        target_clean = self._normalize_dropdown_option_text(target_value)

        if option_clean == target_clean:
            return 10000

        try:
            if float(option_clean) == float(target_clean):
                return 9000
        except ValueError:
            pass

        return None

    def _score_contains_option(self, option_text: str, target_value: str) -> int | None:
        option_clean = self._normalize_dropdown_option_text(option_text).upper()
        target_clean = self._normalize_dropdown_option_text(target_value).upper()

        if option_clean == target_clean:
            return 10000

        if target_clean in option_clean:
            return 8000 - len(option_clean)

        return None

    def _score_weight_option_datasheet(self, option_text: str, target_weight: str) -> int | None:
        target_num = self._safe_float(target_weight)

        if target_num is None:
            return self._score_contains_option(option_text, target_weight)

        option_clean = self._normalize_dropdown_option_text(option_text)

        paren_match = re.search(r"\((.*?)\)", option_clean)
        if paren_match:
            raw_tokens = [t.strip() for t in paren_match.group(1).split(",")]
            for token in raw_tokens:
                token_num = self._safe_float(token)
                if token_num is not None and token_num == target_num:
                    return 10000

        if str(target_weight).strip() in option_clean:
            return 7000 - len(option_clean)

        return None

    def _score_weight_option_blanking(self, option_text: str, target_weight: str) -> int | None:
        target_num = self._safe_float(target_weight)

        if target_num is None:
            return self._score_contains_option(option_text, target_weight)

        option_clean = self._normalize_dropdown_option_text(option_text)

        paren_match = re.search(r"\((.*?)\)", option_clean)
        if paren_match:
            token = paren_match.group(1).strip()
            token_num = self._safe_float(token)
            if token_num is not None and token_num == target_num:
                return 10000

        if self._strip_trailing_zero_for_search(target_weight) in option_clean:
            return 7000 - len(option_clean)

        return None

    def _score_connection_option(self, option_text: str, target_value: str) -> int | None:
        normalized_target = self._normalize_connection_text(target_value)
        normalized_option = self._normalize_connection_text(option_text)

        if not normalized_target or not normalized_option:
            return None

        if normalized_option == normalized_target:
            return 100000

        target_tokens = self._tokenize_connection(normalized_target)
        option_tokens = self._tokenize_connection(normalized_option)

        target_token_set = set(target_tokens)
        option_token_set = set(option_tokens)

        if not target_token_set.issubset(option_token_set):
            return None

        target_numbers = self._extract_number_tokens(normalized_target)
        option_numbers = self._extract_number_tokens(normalized_option)

        score = 50000

        if target_numbers:
            if option_numbers == target_numbers:
                score += 30000
            elif set(target_numbers).issubset(set(option_numbers)):
                score += 15000
            else:
                return None

        if normalized_option.startswith(normalized_target):
            score += 5000

        extra_tokens = len(option_tokens) - len(target_tokens)
        score -= extra_tokens * 500
        score -= len(normalized_option)

        return score

    def _normalize_dropdown_option_text(self, text: str | None) -> str:
        if not text:
            return ""

        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

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

    def _strip_trailing_zero_for_search(self, value: str) -> str:
        try:
            return str(float(value)).rstrip("0").rstrip(".")
        except ValueError:
            return value.strip()

    def _safe_float(self, value: str | None) -> float | None:
        if value is None:
            return None

        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            return None

    def _wait_for_connection_loaded(self) -> None:
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
            timeout=20000,
        )

    def _extract_connection_performance(self) -> dict[str, Any]:
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

    def _wait_for_blanking_dimensions_loaded(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                const txt = document.body.innerText || "";
                return txt.includes("Blanking Dimensions")
                    && txt.includes("Selected Product")
                    && txt.includes("Box")
                    && txt.includes("Pin")
                    && txt.includes("Inside Diameter Min")
                    && txt.includes("Outside Diameter Max");
            }
            """,
            timeout=20000,
        )

    def _extract_blanking_dimensions(self, connection_type: str) -> dict[str, Any]:
        body_text = self.page.locator("body").inner_text(timeout=5000)
        normalized = self._normalize_text(body_text)

        if connection_type == "BOX":
            section_text = self._extract_section(
                text=normalized,
                start_label="Box",
                end_candidates=["Pin"],
            )
        elif connection_type == "PIN":
            section_text = self._extract_section(
                text=normalized,
                start_label="Pin",
                end_candidates=[],
            )
        else:
            raise RuntimeError(f"Unsupported TSH connection type: {connection_type}")

        outside_min = self._extract_first_number_after_label(section_text, "Outside Diameter Min")
        outside_max = self._extract_first_number_after_label(section_text, "Outside Diameter Max")
        inside_min = self._extract_first_number_after_label(section_text, "Inside Diameter Min")
        inside_max = self._extract_first_number_after_label(section_text, "Inside Diameter Max")

        if not outside_min or not outside_max:
            raise RuntimeError(f"TSH blanking {connection_type} missing Outside Diameter Min/Max")

        if not inside_min or not inside_max:
            raise RuntimeError(f"TSH blanking {connection_type} missing Inside Diameter Min/Max")

        return {
            "od": {
                "min": outside_min,
                "max": outside_max,
            },
            "id": {
                "min": inside_min,
                "max": inside_max,
            },
        }

    def _extract_selected_product_drift(self) -> str | None:
        body_text = self.page.locator("body").inner_text(timeout=5000)
        normalized = self._normalize_text(body_text)

        selected_product_section = self._extract_section(
            text=normalized,
            start_label="Selected Product",
            end_candidates=["Box", "Pin"],
        )

        pattern = r"Drift\s*\(in\)\s+([+\-]?\d+(?:,\d{3})*(?:\.\d+)?)"
        match = re.search(pattern, selected_product_section, flags=re.IGNORECASE)

        if match:
            return match.group(1)

        raise RuntimeError(
            f"Could not extract TSH Drift from Selected Product section: "
            f"{selected_product_section[:500]}"
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