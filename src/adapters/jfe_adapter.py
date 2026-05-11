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
# 当前版本实现：
# 1. datasheet_generator 页面：
#    打开页面 → 根据 mapped_data 按顺序选择 6 个字段
#    → 抓取 Joint Strength、Compression Rating、Internal Yield Pressure、Collapse Pressure、Drift Diameter
#
# 2. blanking_dimensions 页面：
#    打开页面 → 根据 mapped_data 按顺序选择 4 个字段
#    → 根据 PIN / BOX 抓取 OD、ID，返回 nominal + tol_1 + tol_2 结构
# --------------------------------------------------------------------------------------------------------------------------


class JfeAdapter(BaseAdapter):

    NA = "NA"

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

        self.logger = setup_logger(self.logs_dir, "jfe_adapter_v2.4")

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

        connection = mapped_data.get("connection") or {}
        connection_type = (connection.get("type") or "").upper()

        if connection_type not in {"BOX", "PIN"}:
            raise ValueError(f"JFE mapped_data has unsupported connection.type: {connection_type}")

        # Datasheet flow
        self.open_datasheet_page()
        self._wait_for_datasheet_page_loaded()

        self._select_datasheet_options(mapped_data)
        self._wait_for_datasheet_result_loaded()

        datasheet_result = self.extract_required_data(
            mapped_data=mapped_data,
        )

        # Blanking Dimensions flow
        self.open_blanking_page()
        self._wait_for_blanking_page_loaded()

        self._select_blanking_options(mapped_data)
        self._wait_for_blanking_dimensions_loaded()

        blanking_result = self._extract_blanking_dimensions(connection_type)

        return {
            **datasheet_result,
            **blanking_result,
        }

    # ------------------------------------------------------------------
    # Page open
    # ------------------------------------------------------------------

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

        try:
            self.page.close()
        except Exception:
            pass

        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.set_default_navigation_timeout(self.navigation_timeout_ms)

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

    def _wait_for_datasheet_page_loaded(self) -> None:
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

    def _wait_for_blanking_page_loaded(self) -> None:
        self._wait_for_loading_overlay_hidden()

        self.page.locator("#datasheet_builder").wait_for(
            state="visible",
            timeout=30000,
        )

        # Blanking 页面固定有 4 个下拉框：
        # Connection, Size, Weight, Coupling Type
        self.page.locator("#datasheet_builder select").nth(3).wait_for(
            state="visible",
            timeout=30000,
        )

        self._wait_for_loading_overlay_hidden()

    def _wait_for_loading_overlay_hidden(self) -> None:
        try:
            self.page.wait_for_function(
                """
                () => {
                    const overlays = Array.from(
                        document.querySelectorAll(".loading-overlay")
                    );

                    if (overlays.length === 0) return true;

                    return overlays.every((overlay) => {
                        const style = window.getComputedStyle(overlay);

                        return style.display === "none"
                            || style.visibility === "hidden"
                            || !overlay.classList.contains("is-active");
                    });
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
                const txt = document.body.innerText || "";

                return txt.includes("CONNECTION PERFORMANCE")
                    && txt.includes("Joint Strength")
                    && txt.includes("Compression Rating")
                    && txt.includes("Internal Yield Pressure")
                    && txt.includes("Collapse Pressure");
            }
            """,
            timeout=30000,
        )

    def _wait_for_blanking_dimensions_loaded(self) -> None:
        self._wait_for_loading_overlay_hidden()

        self.page.wait_for_function(
            """
            () => {
                const wrapper = document.querySelector("#blanking_dimensions_wrapper");
                if (!wrapper) return false;

                return Boolean(
                    wrapper.querySelector("#pin_boring")
                    && wrapper.querySelector("#box_boring")
                    && wrapper.querySelector("#turning_diameter")
                );
            }
            """,
            timeout=30000,
        )

    # ------------------------------------------------------------------
    # Datasheet selections
    # ------------------------------------------------------------------

    def _select_datasheet_options(self, mapped_data: dict[str, Any]) -> None:
        selections = self._build_datasheet_selections(mapped_data)

        for field_label, option_text in selections:
            self._select_dropdown_by_field_label(
                field_label=field_label,
                option_text=option_text,
            )

    def _build_datasheet_selections(self, mapped_data: dict[str, Any]) -> list[tuple[str, str]]:
        connection = mapped_data.get("connection") or {}

        selections = [
            ("Connection", connection.get("name")),
            ("Size", connection.get("od")),
            ("Weight", connection.get("weight")),
            ("Grade", connection.get("grade")),
            ("Friction", connection.get("friction")),
            ("Coupling", connection.get("coupling")),
        ]

        missing = [
            field_label
            for field_label, value in selections
            if value is None or str(value).strip() == ""
        ]

        if missing:
            raise ValueError(f"JFE mapped_data missing required datasheet fields: {missing}")

        return [(field_label, str(value).strip()) for field_label, value in selections]

    # ------------------------------------------------------------------
    # Blanking selections
    # ------------------------------------------------------------------

    def _select_blanking_options(self, mapped_data: dict[str, Any]) -> None:
        selections = self._build_blanking_selections(mapped_data)

        for field_label, option_text in selections:
            self._select_dropdown_by_field_label(
                field_label=field_label,
                option_text=option_text,
            )

    def _build_blanking_selections(self, mapped_data: dict[str, Any]) -> list[tuple[str, str]]:
        connection = mapped_data.get("connection") or {}

        selections = [
            ("Connection", connection.get("name")),
            ("Size", connection.get("od")),
            ("Weight", connection.get("weight")),
            ("Coupling Type", connection.get("coupling")),
        ]

        missing = [
            field_label
            for field_label, value in selections
            if value is None or str(value).strip() == ""
        ]

        if missing:
            raise ValueError(f"JFE mapped_data missing required blanking fields: {missing}")

        return [(field_label, str(value).strip()) for field_label, value in selections]

    # ------------------------------------------------------------------
    # Generic select helpers
    # ------------------------------------------------------------------

    def _select_dropdown_by_field_label(
        self,
        field_label: str,
        option_text: str,
    ) -> None:
        select = self._wait_for_select_by_field_label(
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

    def _wait_for_select_by_field_label(
        self,
        field_label: str,
        timeout_ms: int = 30000,
    ):
        elapsed = 0
        interval = 500

        while elapsed < timeout_ms:
            select = self._get_select_by_field_label(field_label)
            if select is not None:
                return select

            self.page.wait_for_timeout(interval)
            elapsed += interval

        raise RuntimeError(f"JFE select not found for field: {field_label}")

    def _get_select_by_field_label(self, field_label: str):
        normalized_target = self._normalize_text(field_label).upper()

        scope = self._get_builder_scope()
        fields = scope.locator(".field")

        try:
            field_count = fields.count()
        except Exception:
            field_count = 0

        for i in range(field_count):
            field = fields.nth(i)

            try:
                if not field.is_visible(timeout=500):
                    continue
            except Exception:
                continue

            select = field.locator("select").first

            try:
                if select.count() == 0 or not select.is_visible(timeout=500):
                    continue
            except Exception:
                continue

            label_text = ""
            try:
                label = field.locator("label").first
                if label.count() > 0:
                    label_text = self._normalize_text(label.text_content(timeout=500))
            except Exception:
                label_text = ""

            if label_text.upper() == normalized_target:
                return select

            option_texts = self._get_select_option_texts(select)
            normalized_options = {
                self._normalize_text(text).upper()
                for text in option_texts
            }

            if normalized_target in normalized_options:
                return select

        return None

    def _get_builder_scope(self):
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

        raise RuntimeError("Could not find JFE builder scope.")

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
                text = self._normalize_text(raw_text)
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

        target_normalized = self._normalize_text(target_text)
        target_upper = target_normalized.upper()
        target_number = self._extract_first_number_as_float(target_normalized)

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
                option_text = self._normalize_text(raw_text)
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

        option_number = self._extract_first_number_as_float(option_text)

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
        connection_performance = self._extract_connection_performance()

        drift_extraction = bool(mapped_data.get("drift_extraction"))

        drift = self.NA
        if drift_extraction:
            drift = self._extract_drift_diameter()

        return {
            "tensile": connection_performance.get("tensile"),
            "compression": connection_performance.get("compression"),
            "burst": connection_performance.get("burst"),
            "collapse": connection_performance.get("collapse"),
            "drift": drift,
        }

    def _extract_connection_performance(self) -> dict[str, str | None]:
        return {
            "tensile": self._extract_first_number_from_table_field(
                identifier="CONNECTION PERFORMANCE",
                field_label="Joint Strength",
            ),
            "compression": self._extract_first_number_from_table_field(
                identifier="CONNECTION PERFORMANCE",
                field_label="Compression Rating",
            ),
            "burst": self._extract_first_number_from_table_field(
                identifier="CONNECTION PERFORMANCE",
                field_label="Internal Yield Pressure",
            ),
            "collapse": self._extract_first_number_from_table_field(
                identifier="CONNECTION PERFORMANCE",
                field_label="Collapse Pressure",
            ),
        }

    def _extract_drift_diameter(self) -> str | None:
        return self._extract_first_number_from_table_field(
            identifier="PIPE",
            field_label="Drift Diameter",
        )

    def _extract_first_number_from_table_field(
        self,
        identifier: str,
        field_label: str,
    ) -> str | None:
        raw_value = self._extract_table_field_value(
            identifier=identifier,
            field_label=field_label,
        )

        if raw_value is None:
            raise RuntimeError(
                f"Could not extract JFE field. "
                f"identifier=[{identifier}], field_label=[{field_label}]"
            )

        value = self._extract_first_number(raw_value)
        if value is None:
            raise RuntimeError(
                f"Could not extract numeric value from JFE field. "
                f"identifier=[{identifier}], field_label=[{field_label}], raw_value=[{raw_value}]"
            )

        return value

    def _extract_table_field_value(
        self,
        identifier: str,
        field_label: str,
    ) -> str | None:
        return self.page.evaluate(
            """
            ({ identifier, fieldLabel }) => {
                const normalize = (text) => {
                    return (text || "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                };

                const identifierTarget = normalize(identifier);
                const fieldTarget = normalize(fieldLabel);

                const tbodies = Array.from(
                    document.querySelectorAll("#datasheet_page tbody")
                );

                const targetTbody = tbodies.find((tbody) => {
                    const identifierEl = tbody.querySelector(".identifier");
                    if (!identifierEl) return false;

                    const identifierText = normalize(identifierEl.innerText);
                    return identifierText.includes(identifierTarget);
                });

                if (!targetTbody) {
                    return null;
                }

                const rows = Array.from(targetTbody.querySelectorAll("tr"));

                for (const row of rows) {
                    const rowStyle = window.getComputedStyle(row);
                    if (rowStyle.display === "none") {
                        continue;
                    }

                    const cells = Array.from(row.querySelectorAll("td"));

                    for (let i = 0; i < cells.length; i++) {
                        const cell = cells[i];

                        if (cell.classList.contains("identifier")) {
                            continue;
                        }

                        const cellText = normalize(cell.innerText);

                        if (cellText === fieldTarget || cellText.includes(fieldTarget)) {
                            for (let j = i + 1; j < cells.length; j++) {
                                const valueText = (cells[j].innerText || "")
                                    .replace(/\\s+/g, " ")
                                    .trim();

                                if (valueText) {
                                    return valueText;
                                }
                            }
                        }
                    }
                }

                return null;
            }
            """,
            {
                "identifier": identifier,
                "fieldLabel": field_label,
            },
        )

    # ------------------------------------------------------------------
    # Blanking extraction
    # ------------------------------------------------------------------

    def _extract_blanking_dimensions(self, connection_type: str) -> dict[str, Any]:
        return {
            "od": self._extract_blanking_od(connection_type),
            "id": self._extract_blanking_id(connection_type),
            "external_length": None,
            "internal_length": None,
        }

    def _extract_blanking_id(self, connection_type: str) -> dict[str, str]:
        selector = "#pin_boring" if connection_type == "PIN" else "#box_boring"

        raw_data = self.page.evaluate(
            """
            (selector) => {
                const root = document.querySelector(selector);
                if (!root) return null;

                const top = root.querySelector(".top");
                const columns = Array.from(root.querySelectorAll(".columns .column"));

                return {
                    nominal: top ? top.innerText : null,
                    tolerances: columns.map(col => col.innerText || "")
                };
            }
            """,
            selector,
        )

        if not raw_data:
            raise RuntimeError(f"Could not find JFE blanking ID section: {selector}")

        return self._build_nominal_tolerance_dimension(
            raw_data=raw_data,
            field_name=f"JFE blanking ID {connection_type}",
        )

    def _extract_blanking_od(self, connection_type: str) -> dict[str, str]:
        raw_data = self.page.evaluate(
            """
            (connectionType) => {
                const root = document.querySelector("#turning_diameter");
                if (!root) return null;

                const topColumns = Array.from(
                    root.querySelectorAll(".top .columns .column")
                );

                const toleranceColumns = Array.from(
                    root.querySelectorAll(":scope > .columns .column")
                );

                const isPin = connectionType === "PIN";

                const nominalText = isPin
                    ? (topColumns[0] ? topColumns[0].innerText : null)
                    : (topColumns[1] ? topColumns[1].innerText : null);

                const toleranceTexts = isPin
                    ? toleranceColumns.slice(0, 2).map(col => col.innerText || "")
                    : toleranceColumns.slice(2, 4).map(col => col.innerText || "");

                return {
                    nominal: nominalText,
                    tolerances: toleranceTexts
                };
            }
            """,
            connection_type,
        )

        if not raw_data:
            raise RuntimeError("Could not find JFE blanking OD section: #turning_diameter")

        return self._build_nominal_tolerance_dimension(
            raw_data=raw_data,
            field_name=f"JFE blanking OD {connection_type}",
        )

    def _build_nominal_tolerance_dimension(
        self,
        raw_data: dict[str, Any],
        field_name: str,
    ) -> dict[str, str]:
        nominal = self._extract_first_number(raw_data.get("nominal"))

        tolerances = [
            self._extract_first_number(text)
            for text in raw_data.get("tolerances", [])
        ]
        tolerances = [value for value in tolerances if value is not None]

        if nominal is None or len(tolerances) < 2:
            raise RuntimeError(
                f"Invalid {field_name} data. raw_data={raw_data}"
            )

        return {
            "nominal": self._format_nominal(nominal),
            "tol_1": tolerances[0],
            "tol_2": tolerances[1],
        }

    def _format_nominal(self, value: str) -> str:
        try:
            return f"{float(value.replace(',', '').strip()):.3f}"
        except ValueError:
            return value.strip()

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _normalize_text(self, text: str | None) -> str:
        if not text:
            return ""

        text = text.replace("\u00a0", " ")
        text = text.replace("º", "°")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalize_for_contains(self, text: str) -> str:
        text = self._normalize_text(text)
        text = text.replace(" ", "")
        text = text.replace("-", "")
        text = text.replace("_", "")
        return text.upper()

    def _extract_first_number(self, text: str | None) -> str | None:
        if not text:
            return None

        match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text.replace(",", ""))
        if not match:
            return None

        return match.group(0)

    def _extract_first_number_as_float(self, text: str | None) -> float | None:
        value = self._extract_first_number(text)
        if value is None:
            return None

        try:
            return float(value)
        except ValueError:
            return None