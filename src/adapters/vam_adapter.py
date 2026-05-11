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

from src.adapters.base_adapter import BaseAdapter
from src.utils import ensure_dir, setup_logger


class VamAdapter(BaseAdapter):

    DROPDOWN_INDEX_MAP = {
        "OD (in)": 0,
        "Weight / WT (lb/ft)": 1,
        "Material Family": 3,
        "Yield Strength (ksi)": 4,
        "Grade": 5,
        "Drift Option": 6,
    }

    DEFAULT_DRIFT_OPTION = "API Drift"
    NA = "NA"

    def __init__(
        self,
        base_url: str,
        configurator_url: str,
        logs_dir: Path,
        headless: bool = False,
        slow_mo: int = 300,
        timeout_ms: int = 10000,
    ) -> None:
        self.base_url = base_url
        self.configurator_url = configurator_url
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms

        ensure_dir(self.logs_dir)

        self.logger = setup_logger(self.logs_dir, "vam_adapter_v2.3")

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
        connection_data = mapped_data.get("connection") or {}
        connection_name = connection_data.get("name")
        result_index = int(mapped_data.get("result_index", 0))

        if not connection_name:
            raise ValueError("Mapped data is missing connection.name")

        self.open_configurator()
        self.handle_cookie_popup_if_any()

        filters = self._build_filters_from_mapped_data(mapped_data)

        for field_label, value in filters.items():
            if value is None:
                continue
            self.select_dropdown_option_by_index(field_label, value)

        self.select_connection(connection_name)
        self.wait_for_results()

        cds_page = self.open_result_cds(result_index)
        self._wait_for_cds_content_loaded(cds_page)

        return self.extract_required_data(
            cds_page=cds_page,
            mapped_data=mapped_data,
        )

    def _build_filters_from_mapped_data(self, mapped_data: dict[str, Any]) -> dict[str, Any]:
        connection = mapped_data.get("connection") or {}

        return {
            "OD (in)": connection.get("od"),
            "Weight / WT (lb/ft)": connection.get("weight"),
            # "Material Family": connection.get("material_family"),
            "Yield Strength (ksi)": connection.get("yield_strength"),
            # "Grade" 暂不考虑
            "Drift Option": self.DEFAULT_DRIFT_OPTION,
        }

    def open_configurator(self) -> None:
        self.page.goto(self.configurator_url, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    def handle_cookie_popup_if_any(self) -> None:
        candidates = [
            "Accept",
            "Accept All",
            "I Accept",
            "Allow all",
            "Got it",
            "Agree",
            "Continue",
        ]

        for text in candidates:
            try:
                locator = self.page.get_by_role("button", name=text, exact=True).first
                if locator.is_visible(timeout=1200):
                    locator.click(force=True)
                    self.page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

    def select_dropdown_option_by_index(self, field_label: str, option_text: str) -> None:
        if field_label not in self.DROPDOWN_INDEX_MAP:
            raise KeyError(f"Field label not found in DROPDOWN_INDEX_MAP: {field_label}")

        dropdown_index = self.DROPDOWN_INDEX_MAP[field_label]
        trigger = self._get_dropdown_trigger_by_index(dropdown_index, field_label)

        try:
            trigger.scroll_into_view_if_needed()
            self.page.wait_for_timeout(300)
            trigger.click(force=True)
        except Exception as e:
            raise RuntimeError(f"Failed to click dropdown trigger for field [{field_label}]") from e

        if field_label == "Weight / WT (lb/ft)":
            self._select_weight_option_from_overlay(option_text, field_label)
        else:
            self._select_option_from_overlay(option_text, field_label)

        self.page.wait_for_timeout(1200)
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    def _get_filter_area(self):
        candidates = [
            self.page.locator("div.filter").first,
            self.page.locator("app-configurator .filter").first,
            self.page.locator("app-configurator").locator(".filter").first,
        ]

        for candidate in candidates:
            try:
                if candidate.is_visible(timeout=5000):
                    return candidate
            except Exception:
                continue

        raise RuntimeError("Could not find filter area")

    def _get_dropdown_trigger_by_index(self, dropdown_index: int, field_label: str):
        filter_area = self._get_filter_area()

        candidates = [
            filter_area.locator("[role='combobox']"),
            filter_area.locator("mat-select"),
            filter_area.locator("input"),
            filter_area.locator(".mat-select-trigger"),
            filter_area.locator(".mat-mdc-select-trigger"),
            filter_area.locator(".mat-input-element"),
        ]

        for group in candidates:
            try:
                count = group.count()
                if count > dropdown_index:
                    trigger = group.nth(dropdown_index)
                    if trigger.is_visible(timeout=1500):
                        return trigger
            except Exception:
                continue

        divs = filter_area.locator("div")
        matched_blocks = []

        try:
            div_count = divs.count()
        except Exception:
            div_count = 0

        for i in range(min(div_count, 400)):
            try:
                div = divs.nth(i)
                if not div.is_visible(timeout=100):
                    continue

                text = div.inner_text(timeout=300).strip().lower()
                if text and "select" in text:
                    matched_blocks.append(div)
            except Exception:
                continue

        if len(matched_blocks) > dropdown_index:
            return matched_blocks[dropdown_index]

        raise RuntimeError(f"Could not find dropdown trigger for field [{field_label}] at index [{dropdown_index}]")

    def _select_option_from_overlay(self, option_text: str, field_label: str) -> None:
        overlay_candidates = [
            self.page.locator("div[role='listbox']").first,
            self.page.locator(".mat-autocomplete-panel").first,
            self.page.locator(".cdk-overlay-pane").first,
        ]

        overlay_found = False
        for overlay in overlay_candidates:
            try:
                overlay.wait_for(state="visible", timeout=5000)
                overlay_found = True
                break
            except Exception:
                continue

        if not overlay_found:
            raise RuntimeError(f"Dropdown overlay not found for field [{field_label}]")

        option_candidates = [
            self.page.locator("mat-option[role='option']").filter(has_text=option_text).first,
            self.page.locator("mat-option .mat-option-text").filter(has_text=option_text).first,
            self.page.locator(".mat-option-text").filter(has_text=option_text).first,
            self.page.locator("[role='option']").filter(has_text=option_text).first,
            self.page.get_by_text(option_text, exact=False).first,
        ]

        for option in option_candidates:
            try:
                option.wait_for(state="visible", timeout=4000)
                option.scroll_into_view_if_needed()
                self.page.wait_for_timeout(300)
                option.click(force=True)
                return
            except Exception:
                continue

        raise RuntimeError(f"Could not select option [{option_text}] for field [{field_label}]")

    def _select_weight_option_from_overlay(self, weight_text: str, field_label: str) -> None:
        overlay_candidates = [
            self.page.locator("div[role='listbox']").first,
            self.page.locator(".mat-autocomplete-panel").first,
            self.page.locator(".cdk-overlay-pane").first,
        ]

        overlay_found = False
        for overlay in overlay_candidates:
            try:
                overlay.wait_for(state="visible", timeout=5000)
                overlay_found = True
                break
            except Exception:
                continue

        if not overlay_found:
            raise RuntimeError(f"Dropdown overlay not found for field [{field_label}]")

        prefix = f"{weight_text}#"

        option_candidates = self.page.locator("[role='option'], mat-option")
        matched_options = []

        try:
            count = option_candidates.count()
        except Exception:
            count = 0

        for i in range(count):
            try:
                option = option_candidates.nth(i)
                if not option.is_visible(timeout=500):
                    continue

                text = option.inner_text(timeout=1000).strip()
                if text.startswith(prefix):
                    matched_options.append(option)
            except Exception:
                continue

        if len(matched_options) == 0:
            raise RuntimeError(
                f"No weight option found for prefix [{prefix}] under current OD/material context."
            )

        if len(matched_options) > 1:
            raise RuntimeError(f"Multiple weight options found for prefix [{prefix}]")

        target_option = matched_options[0]
        target_option.scroll_into_view_if_needed()
        self.page.wait_for_timeout(300)
        target_option.click(force=True)

    def select_connection(self, connection_name: str) -> None:
        container = self._get_connection_container()

        try:
            search_area = container.locator(".connection-search").first
            search_input_candidates = [
                search_area.locator("input").first,
                search_area.locator("input[type='search']").first,
                search_area.locator("input[placeholder*='Search']").first,
            ]

            for search_input in search_input_candidates:
                try:
                    if search_input.is_visible(timeout=3000):
                        search_input.click()
                        search_input.fill(connection_name)
                        self.page.wait_for_timeout(500)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        self._click_connection_card(container, connection_name)

        self.page.wait_for_timeout(1500)
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

    def _get_connection_container(self):
        candidates = [
            self.page.locator("div.connection-container").first,
            self.page.locator(".connections .connection-container").first,
            self.page.locator(".connections").locator(".connection-container").first,
        ]

        for candidate in candidates:
            try:
                if candidate.is_visible(timeout=3000):
                    return candidate
            except Exception:
                continue

        raise RuntimeError("Could not find connection container")

    def _click_connection_card(self, container, connection_name: str) -> None:
        display = container.locator(".connection-display").first

        text_candidates = [
            connection_name,
            connection_name.replace("VAM ", "VAM® "),
            connection_name.replace(" ", "\u00a0"),
        ]

        for text in text_candidates:
            try:
                label = display.get_by_text(text, exact=False).first
                label.wait_for(state="visible", timeout=3000)
                label.scroll_into_view_if_needed()

                card_candidates = [
                    label.locator("xpath=ancestor::button[1]").first,
                    label.locator("xpath=ancestor::a[1]").first,
                    label.locator("xpath=ancestor::*[@role='button'][1]").first,
                    label.locator("xpath=ancestor::div[contains(@class,'card')][1]").first,
                    label.locator("xpath=ancestor::div[contains(@class,'item')][1]").first,
                    label.locator("xpath=ancestor::div[contains(@class,'connection')][1]").first,
                ]

                for card in card_candidates:
                    try:
                        if card.is_visible(timeout=1500):
                            card.scroll_into_view_if_needed()
                            self.page.wait_for_timeout(300)
                            card.click(force=True)
                            return
                    except Exception:
                        continue

                label.click(force=True)
                return

            except Exception:
                continue

        raise RuntimeError(f"Could not click connection card [{connection_name}]")

    def wait_for_results(self) -> None:
        candidates = [
            self.page.locator("[data-cy='configurator-resultsviewport']").first,
            self.page.locator("cdk-virtual-scroll-viewport").first,
            self.page.locator("configurator-result-card").first,
            self.page.locator("[data-cy='view-cds-button']").first,
        ]

        for candidate in candidates:
            try:
                candidate.wait_for(state="visible", timeout=3000)
                return
            except Exception:
                continue

        raise RuntimeError("No results detected after applying filters")

    def open_result_cds(self, result_index: int = 0) -> Page:
        viewport_candidates = [
            self.page.locator("[data-cy='configurator-resultsviewport']").first,
            self.page.locator("cdk-virtual-scroll-viewport").first,
        ]

        viewport = None
        for candidate in viewport_candidates:
            try:
                if candidate.is_visible(timeout=5000):
                    viewport = candidate
                    break
            except Exception:
                continue

        if viewport is None:
            raise RuntimeError("Could not find results viewport")

        result_cards = viewport.locator("configurator-result-card")
        try:
            result_cards.first.wait_for(state="visible", timeout=10000)
        except Exception as e:
            raise RuntimeError("No visible result cards found") from e

        count = result_cards.count()

        if count == 0:
            raise RuntimeError("No result cards available")

        if result_index >= count:
            raise IndexError(
                f"Requested result_index={result_index}, but only {count} visible result cards found"
            )

        target_card = result_cards.nth(result_index)
        target_card.scroll_into_view_if_needed()
        self.page.wait_for_timeout(500)

        button_candidates = [
            target_card.locator("[data-cy='view-cds-button']").first,
            target_card.locator(".view-cds").first,
            target_card.get_by_text("View CDS", exact=False).first,
        ]

        for btn in button_candidates:
            try:
                if not btn.is_visible(timeout=3000):
                    continue

                btn.scroll_into_view_if_needed()
                self.page.wait_for_timeout(300)

                current_page = self.page
                old_url = current_page.url
                pages_before = list(self.context.pages)

                btn.click(force=True)
                self.page.wait_for_timeout(2000)

                new_url = current_page.url
                if new_url != old_url and "specific-product" in new_url:
                    try:
                        current_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    try:
                        current_page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    return current_page

                pages_after = list(self.context.pages)
                if len(pages_after) > len(pages_before):
                    cds_page = pages_after[-1]
                    cds_page.set_default_timeout(self.timeout_ms)

                    try:
                        cds_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    try:
                        cds_page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    return cds_page

                try:
                    current_page.wait_for_url("**/product/specific-product/**", timeout=5000)
                    return current_page
                except Exception:
                    pass

            except Exception:
                continue

        raise RuntimeError(f"Failed to click View CDS for result index [{result_index}]")

    def _wait_for_loader_to_disappear(self, page: Page, timeout: int = 15000) -> None:
        loader_candidates = [
            page.locator("[data-cy='cds-component-ui-loader']").first,
            page.locator("ui-loader").first,
            page.locator(".spinner").first,
        ]

        for loader in loader_candidates:
            try:
                if loader.is_visible(timeout=1500):
                    loader.wait_for(state="hidden", timeout=timeout)
                    return
            except Exception:
                continue

    def _poll_page_text_until_ready(
        self,
        page: Page,
        ready_patterns: list[str],
        timeout_ms: int = 20000,
        interval_ms: int = 1000,
        log_label: str = "",
    ) -> str:
        elapsed = 0
        last_text = ""

        body = page.locator("body").first

        while elapsed < timeout_ms:
            try:
                text = body.inner_text(timeout=3000).strip()
                last_text = text

                normalized = self._normalize_text_for_parsing(text)
                for pattern in ready_patterns:
                    if re.search(pattern, normalized, flags=re.IGNORECASE):
                        return text
            except Exception:
                pass

            page.wait_for_timeout(interval_ms)
            elapsed += interval_ms

        raise RuntimeError(
            f"Timed out waiting for page content readiness in [{log_label}]. "
            f"Last text snippet: {last_text[:500]}"
        )

    def _wait_for_cds_content_loaded(self, cds_page: Page) -> None:
        self._wait_for_loader_to_disappear(cds_page, timeout=15000)

        self._poll_page_text_until_ready(
            page=cds_page,
            ready_patterns=[r"Joint Performances", r"Connection Properties", r"Pipe Body Properties"],
            timeout_ms=10000,
            interval_ms=1000,
            log_label="cds_page_shell",
        )

        self._poll_page_text_until_ready(
            page=cds_page,
            ready_patterns=[r"\bpsi\b", r"\bklb\b"],
            timeout_ms=25000,
            interval_ms=1000,
            log_label="cds_page_values",
        )

    def _wait_for_blanking_content_loaded(self, cds_page: Page, connection_type: str) -> None:
        self._wait_for_loader_to_disappear(cds_page, timeout=15000)

        if connection_type == "BOX":
            patterns = [r"\bBOX\b", r"\bBED\b", r"\bBID\b", r"\bMBEL\b", r"\bMBIL\b", r"\bin\.\b"]
            label = "blanking_box"
        elif connection_type == "PIN":
            patterns = [r"\bPIN\b", r"\bPED\b", r"\bPID\b", r"\bMPEL\b", r"\bMPIL\b", r"\bin\.\b"]
            label = "blanking_pin"
        else:
            raise RuntimeError(f"Unsupported connection type for blanking wait: {connection_type}")

        self._poll_page_text_until_ready(
            page=cds_page,
            ready_patterns=patterns,
            timeout_ms=20000,
            interval_ms=1000,
            log_label=label,
        )

    def extract_required_data(
        self,
        cds_page: Page,
        mapped_data: dict[str, Any],
    ) -> dict[str, Any]:
        connection = mapped_data.get("connection") or {}
        connection_type = (connection.get("type") or "").upper()

        drift_extraction = bool(mapped_data.get("drift_extraction"))

        drift_size: dict[str, Any] = {
            "drift": self.NA,
        }
        if drift_extraction:
            drift_size = {
                "drift": self._extract_drift_size(cds_page),
            }

        joint_performances = self._extract_joint_performances(cds_page)

        self._open_blanking_dimensions_tab(cds_page)
        self._wait_for_blanking_content_loaded(cds_page, connection_type)

        blanking_dimensions = self._extract_blanking_dimensions(
            cds_page=cds_page,
            connection_type=connection_type,
        )

        return {
            **joint_performances,
            **blanking_dimensions,
            **drift_size,
        }

    def _extract_joint_performances(self, cds_page: Page) -> dict[str, str | None]:
        pairs: dict[str, str] = {}

        rows = cds_page.locator("[data-cy^='cds-card-data']")
        try:
            row_count = rows.count()
        except Exception:
            row_count = 0

        for idx in range(row_count):
            try:
                row = rows.nth(idx)

                label_locator = row.locator("[data-cy^='cds-card-label']").first
                value_cast_locator = row.locator("[data-cy^='cds-card-value-cast']").first
                unit_locator = row.locator("[data-cy^='cds-card-unit']").first

                if label_locator.count() == 0 or value_cast_locator.count() == 0:
                    continue

                label = label_locator.inner_text(timeout=2000).strip()
                value = value_cast_locator.inner_text(timeout=2000).strip()

                unit = ""
                try:
                    if unit_locator.count() > 0:
                        unit = unit_locator.inner_text(timeout=1000).strip()
                except Exception:
                    unit = ""

                if not label or not value:
                    continue

                normalized_label = self._normalize_text_for_parsing(label)
                normalized_value = self._normalize_text_for_parsing(f"{value} {unit}".strip())

                if self._is_joint_performance_label(normalized_label):
                    pairs[normalized_label] = self._extract_first_number(normalized_value)

            except Exception:
                continue

        return {
            "tensile": self._lookup_value_by_contains(
                pairs, "Tension Strength, with Sealability"
            ),
            "compression": self._lookup_value_by_contains(
                pairs, "Compression Strength, with Sealability"
            ),
            "burst": self._lookup_value_by_contains(
                pairs, "Internal Pressure Resistance"
            ),
            "collapse": self._lookup_value_by_contains(
                pairs, "External Pressure Resistance"
            ),
        }

    def _extract_drift_size(self, cds_page: Page) -> str | None:
        rows = cds_page.locator("[data-cy^='cds-card-data']")

        try:
            row_count = rows.count()
        except Exception:
            row_count = 0

        for idx in range(row_count):
            try:
                row = rows.nth(idx)

                label_locator = row.locator("[data-cy^='cds-card-label']").first
                value_cast_locator = row.locator("[data-cy^='cds-card-value-cast']").first
                unit_locator = row.locator("[data-cy^='cds-card-unit']").first

                if label_locator.count() == 0 or value_cast_locator.count() == 0:
                    continue

                label = label_locator.inner_text(timeout=2000).strip()
                value = value_cast_locator.inner_text(timeout=2000).strip()

                unit = ""
                try:
                    if unit_locator.count() > 0:
                        unit = unit_locator.inner_text(timeout=1000).strip()
                except Exception:
                    unit = ""

                if not label or not value:
                    continue

                normalized_label = self._normalize_text_for_parsing(label).lower()
                normalized_value = self._normalize_text_for_parsing(f"{value} {unit}".strip())

                if normalized_label == "drift":
                    return self._extract_first_number(normalized_value)

            except Exception:
                continue

        raise RuntimeError("Could not extract VAM Drift from Pipe Body Properties.")

    def _open_blanking_dimensions_tab(self, cds_page: Page) -> None:
        tab_candidates = [
            cds_page.get_by_role("tab", name="Blanking Dimensions"),
            cds_page.locator("[role='tab']").filter(has_text="Blanking Dimensions").first,
            cds_page.get_by_text("Blanking Dimensions", exact=False).first,
        ]

        for tab in tab_candidates:
            try:
                if tab.is_visible(timeout=3000):
                    tab.click(force=True)
                    cds_page.wait_for_timeout(500)
                    return
            except Exception:
                continue

        raise RuntimeError("Could not open Blanking Dimensions tab.")

    def _extract_blanking_dimensions(
        self,
        cds_page: Page,
        connection_type: str,
    ) -> dict[str, Any]:
        body_text = cds_page.locator("body").inner_text(timeout=5000)
        normalized = self._normalize_text_for_parsing(body_text)

        if connection_type == "BOX":
            section_text = self._extract_section(
                text=normalized,
                start_label="BOX",
                end_candidates=["PIN", "The availability of blanking dimensions"],
            )
            return {
                "od": self._extract_dimension_triplet(section_text, "BED"),
                "id": self._extract_dimension_triplet(section_text, "BID"),
                "external_length": self._extract_min_length_value(section_text, "MBEL"),
                "internal_length": self._extract_min_length_value(section_text, "MBIL"),
            }

        if connection_type == "PIN":
            section_text = self._extract_section(
                text=normalized,
                start_label="PIN",
                end_candidates=["The availability of blanking dimensions", "WARNING"],
            )
            return {
                "od": self._extract_dimension_triplet(section_text, "PED"),
                "id": self._extract_dimension_triplet(section_text, "PID"),
                "external_length": self._extract_min_length_value(section_text, "MPEL"),
                "internal_length": self._extract_min_length_value(section_text, "MPIL"),
            }

        raise RuntimeError(f"Unsupported connection type for blanking extraction: {connection_type}")

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

    def _extract_dimension_triplet(self, section_text: str, label: str) -> dict[str, str | None]:
        normalized = self._normalize_text_for_parsing(section_text)

        pattern = (
            rf"{re.escape(label)}\s+"
            rf"([+\-]?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*in\.\s+"
            rf"([+\-]?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*in\.\s*/\s*"
            rf"([+\-]?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*in\."
        )

        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            raise RuntimeError(f"Could not extract blanking dimension for label [{label}] from text: {normalized}")

        return {
            "nominal": match.group(1),
            "tol_1": match.group(2),
            "tol_2": match.group(3),
        }

    def _extract_min_length_value(self, section_text: str, label: str) -> str | None:
        normalized = self._normalize_text_for_parsing(section_text)

        pattern = (
            rf"{re.escape(label)}\s+"
            rf"(?:min\.\s*)?"
            rf"([+\-]?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*in\."
        )

        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            raise RuntimeError(f"Could not extract blanking length for label [{label}] from text: {normalized}")

        return match.group(1)

    def _extract_first_number(self, text: str) -> str | None:
        match = re.search(r"([+\-]?\d+(?:,\d{3})*(?:\.\d+)?)", text)
        if match:
            return match.group(1)
        return None

    def _lookup_value_by_contains(self, pairs: dict[str, str], label: str) -> str | None:
        normalized_target = self._normalize_text_for_parsing(label).lower()

        for k, v in pairs.items():
            if normalized_target in k.lower():
                return v
        return None

    def _is_joint_performance_label(self, label: str) -> bool:
        candidates = [
            "Tension Strength, with Sealability",
            "Compression Strength, with Sealability",
            "Internal Pressure Resistance",
            "External Pressure Resistance",
            "Maximum Bending, Structural",
            "Maximum Bending, with Sealability",
            "Maximum Load on Coupling Face",
        ]

        normalized_label = self._normalize_text_for_parsing(label).lower()

        for candidate in candidates:
            if self._normalize_text_for_parsing(candidate).lower() in normalized_label:
                return True

        return False

    def _normalize_text_for_parsing(self, text: str) -> str:
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()