from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import (
    sync_playwright,
    Page,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
)

from src.adapters.base_adapter import BaseAdapter
from src.utils import ensure_dir, setup_logger


class HtAdapter(BaseAdapter):

    NA = "NA"

    CONNECTION_STYLE = "Threaded and Coupled"

    REPORT_SECTION_LABELS = {
        "Pipe Body Data",
        "Connection Data",
        "Operational Data",
        "Notes",
    }

    BLANKING_COLUMNS = {
        "PIN": {
            "id": 159.0,
            "od": 216.0,
            "internal_length": [274.0, 331.0],
            "external_length": [389.0, 446.0],
        },
        "BOX": {
            "id": 562.0,
            "od": 619.0,
            "internal_length": [735.0, 792.0],
            "external_length": [850.0, 907.0],
        },
    }

    def __init__(
        self,
        base_url: str,
        datasheet_url: str,
        logs_dir: Path,
        headless: bool = False,
        slow_mo: int = 300,
        timeout_ms: int = 10000,
        navigation_timeout_ms: int = 60000,
    ) -> None:
        self.base_url = base_url
        self.datasheet_url = datasheet_url
        self.logs_dir = logs_dir
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms

        ensure_dir(self.logs_dir)

        self.logger = setup_logger(self.logs_dir, "ht_adapter_v2.6")

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
        self.logger.info("Starting HT flow")
        self.logger.info("Mapped data: %s", mapped_data)

        connection = mapped_data.get("connection") or {}

        connection_name = connection.get("name")
        od_value = connection.get("od")
        weight_value = connection.get("weight")

        if not connection_name or not od_value or not weight_value:
            raise ValueError(
                "HT mapped_data missing one of required fields: "
                "connection.name, connection.od, connection.weight"
            )

        connection_type = self._map_connection_type(connection_name)
        material_grade = self._map_material_grade(mapped_data)

        if not material_grade:
            raise ValueError(
                "HT mapped_data missing material grade information. "
                "Expected connection.material_family + connection.yield_strength."
            )

        self.open_datasheet_page()
        self._wait_for_search_page_loaded()

        self._select_search_options(
            connection_type=connection_type,
            od_value=str(od_value).strip(),
            weight_value=str(weight_value).strip(),
            material_grade=material_grade,
        )

        self._click_filter_and_open_report()
        self._wait_for_report_loaded()

        datasheet_result = self.extract_required_data(mapped_data)

        self._open_blanking_sheet_from_datasheet()
        self._wait_for_blanking_report_loaded()

        blanking_result = self.extract_blanking_dimensions(mapped_data)

        return {
            **datasheet_result,
            **blanking_result,
        }

    def open_datasheet_page(self) -> None:
        self.logger.info("Opening HT datasheet search page: %s", self.datasheet_url)
        self._goto_page(self.datasheet_url)

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

    def _wait_for_search_page_loaded(self) -> None:
        self.page.wait_for_function(
            """
            () => {
                return Boolean(
                    window.jQuery
                    && window.kendo
                    && document.querySelector("#ConnectionStyle")
                    && document.querySelector("#ConnectionType")
                    && document.querySelector("#OD")
                    && document.querySelector("#NominalWeight")
                    && document.querySelector("#MaterialGrade")
                );
            }
            """,
            timeout=30000,
        )

        self._wait_for_kendo_dropdown_ready("ConnectionStyle")
        self._wait_for_kendo_dropdown_data("ConnectionStyle")

    def _wait_for_kendo_dropdown_ready(self, input_id: str) -> None:
        self.page.wait_for_function(
            """
            (inputId) => {
                if (!window.jQuery) return false;
                const ddl = window.jQuery("#" + inputId).data("kendoDropDownList");
                return Boolean(ddl);
            }
            """,
            arg=input_id,
            timeout=30000,
        )

    def _wait_for_kendo_dropdown_data(
        self,
        input_id: str,
        min_count: int = 1,
        timeout_ms: int = 30000,
    ) -> None:
        self.page.wait_for_function(
            """
            ({ inputId, minCount }) => {
                if (!window.jQuery) return false;

                const ddl = window.jQuery("#" + inputId).data("kendoDropDownList");
                if (!ddl) return false;

                const items = ddl.dataSource && ddl.dataSource.view
                    ? ddl.dataSource.view()
                    : [];

                return items && items.length >= minCount;
            }
            """,
            arg={
                "inputId": input_id,
                "minCount": min_count,
            },
            timeout=timeout_ms,
        )

    def _select_search_options(
        self,
        connection_type: str,
        od_value: str,
        weight_value: str,
        material_grade: str,
    ) -> None:
        self._select_kendo_dropdown_by_text(
            input_id="ConnectionStyle",
            target_text=self.CONNECTION_STYLE,
            match_mode="text",
        )

        self._wait_for_kendo_dropdown_data("ConnectionType")

        self._select_kendo_dropdown_by_text(
            input_id="ConnectionType",
            target_text=connection_type,
            match_mode="text",
        )

        self._wait_for_kendo_dropdown_data("OD")

        self._select_kendo_dropdown_by_text(
            input_id="OD",
            target_text=od_value,
            match_mode="numeric",
        )

        self._wait_for_kendo_dropdown_data("NominalWeight")

        self._select_kendo_dropdown_by_text(
            input_id="NominalWeight",
            target_text=weight_value,
            match_mode="numeric",
        )

        self._wait_for_kendo_dropdown_data("MaterialGrade")

        self._select_kendo_dropdown_by_text(
            input_id="MaterialGrade",
            target_text=material_grade,
            match_mode="material",
        )

    def _select_kendo_dropdown_by_text(
        self,
        input_id: str,
        target_text: str,
        match_mode: str,
    ) -> None:
        result = self.page.evaluate(
            """
            async ({ inputId, targetText, matchMode }) => {
                const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                const normalizeText = (value) => {
                    return String(value || "")
                        .replace(/\\u00a0/g, " ")
                        .replace(/\\s+/g, " ")
                        .trim();
                };

                const extractNumber = (value) => {
                    const text = normalizeText(value).replace(/,/g, "");
                    const match = text.match(/[-+]?\\d+(?:\\.\\d+)?/);
                    return match ? Number(match[0]) : null;
                };

                const normalizeMaterial = (value) => {
                    return normalizeText(value)
                        .toUpperCase()
                        .replace(/[\\s\\-_/()]/g, "");
                };

                const extractYieldStrength = (value) => {
                    const text = normalizeText(value).replace(/,/g, "");
                    const matches = text.match(/\\d+(?:\\.\\d+)?/g);

                    if (!matches || matches.length === 0) {
                        return null;
                    }

                    return Number(matches[matches.length - 1]);
                };

                const scoreItem = (itemText) => {
                    const optionText = normalizeText(itemText);
                    const optionUpper = optionText.toUpperCase();
                    const target = normalizeText(targetText);
                    const targetUpper = target.toUpperCase();

                    if (!optionText || !target) return null;

                    if (optionUpper === targetUpper) {
                        return 10000;
                    }

                    if (matchMode === "numeric") {
                        const optionNumber = extractNumber(optionText);
                        const targetNumber = extractNumber(target);

                        if (
                            optionNumber !== null
                            && targetNumber !== null
                            && Math.abs(optionNumber - targetNumber) < 0.000001
                        ) {
                            return 9000 - optionText.length;
                        }

                        return null;
                    }

                    if (matchMode === "material") {
                        const optionMaterial = normalizeMaterial(optionText);
                        const targetMaterial = normalizeMaterial(target);

                        if (optionMaterial === targetMaterial) {
                            return 10000;
                        }

                        const optionYield = extractYieldStrength(optionText);
                        const targetYield = extractYieldStrength(target);

                        if (
                            optionYield !== null
                            && targetYield !== null
                            && Math.abs(optionYield - targetYield) < 0.000001
                        ) {
                            return 5000;
                        }

                        return null;
                    }

                    if (optionUpper.includes(targetUpper)) {
                        return 7000 - optionText.length;
                    }

                    return null;
                };

                const ddl = window.jQuery("#" + inputId).data("kendoDropDownList");

                if (!ddl) {
                    return {
                        ok: false,
                        reason: "Kendo DropDownList not found",
                        inputId,
                    };
                }

                for (let i = 0; i < 20; i++) {
                    const view = ddl.dataSource && ddl.dataSource.view
                        ? ddl.dataSource.view()
                        : [];

                    if (view && view.length > 0) {
                        break;
                    }

                    try {
                        ddl.dataSource.read();
                    } catch (e) {
                        // ignore
                    }

                    await wait(500);
                }

                const data = ddl.dataSource && ddl.dataSource.view
                    ? ddl.dataSource.view()
                    : [];

                let bestItem = null;
                let bestScore = null;

                for (const item of data) {
                    const itemText = normalizeText(item.Text ?? item.text ?? item.Name ?? "");
                    const itemValue = item.Value ?? item.value ?? item.Id ?? itemText;

                    if (!itemText) continue;

                    const score = scoreItem(itemText);
                    if (score === null) continue;

                    if (bestScore === null || score > bestScore) {
                        bestScore = score;
                        bestItem = {
                            text: itemText,
                            value: itemValue,
                        };
                    }
                }

                if (!bestItem) {
                    return {
                        ok: false,
                        reason: "Option not found",
                        inputId,
                        targetText,
                        matchMode,
                        availableOptions: data.map(item =>
                            normalizeText(item.Text ?? item.text ?? item.Name ?? "")
                        ).filter(Boolean),
                    };
                }

                ddl.value(bestItem.value);
                ddl.trigger("change");
                ddl.element.trigger("change");

                return {
                    ok: true,
                    inputId,
                    selectedText: bestItem.text,
                    selectedValue: bestItem.value,
                };
            }
            """,
            {
                "inputId": input_id,
                "targetText": target_text,
                "matchMode": match_mode,
            },
        )

        if not result or not result.get("ok"):
            raise RuntimeError(f"Failed to select HT dropdown option: {result}")

        self.logger.info(
            "Selected HT dropdown %s -> %s",
            input_id,
            result.get("selectedText"),
        )

        self.page.wait_for_timeout(1200)

        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

    def _click_filter_and_open_report(self) -> None:
        self.logger.info("Clicking HT Filter button")

        filter_button = self.page.locator(
            "#searchtable a.k-button:has-text('Filter')"
        ).first

        filter_button.wait_for(state="visible", timeout=15000)
        filter_button.click()

        self._wait_for_result_grid_loaded()

        view_datasheet = self.page.locator(
            "#MasterDataGrid a.k-button[href*='/ConnectorSheets/GenerateReport/']:has-text('View Datasheet')"
        ).first

        view_datasheet.wait_for(state="visible", timeout=30000)

        href = view_datasheet.get_attribute("href")
        if not href:
            raise RuntimeError("HT View Datasheet link found but href is empty.")

        report_url = urljoin(self.base_url, href)

        self.logger.info("Opening HT report page: %s", report_url)

        self._goto_page(report_url)

        self.page.wait_for_function(
            """
            () => {
                return window.location.href.includes("/ConnectorSheets/GenerateReport/");
            }
            """,
            timeout=30000,
        )

    def _wait_for_result_grid_loaded(self) -> None:
        self.logger.info("Waiting for HT result grid to load")

        self.page.wait_for_function(
            """
            () => {
                const grid = document.querySelector("#result-grid");
                const masterGrid = document.querySelector("#MasterDataGrid");

                if (!grid || !masterGrid) return false;

                const gridStyle = window.getComputedStyle(grid);
                if (gridStyle.display === "none" || gridStyle.visibility === "hidden") {
                    return false;
                }

                const viewLink = masterGrid.querySelector(
                    "a[href*='/ConnectorSheets/GenerateReport/']"
                );

                return Boolean(viewLink);
            }
            """,
            timeout=30000,
        )

    def _open_blanking_sheet_from_datasheet(self) -> None:
        self.logger.info("Opening HT blanking sheet from connector sheet page")

        blanking_sheet_link = self.page.locator(
            "a.k-button[href*='/BlankingSheets/GenerateReport/']:has-text('View Blanking Sheet')"
        ).first

        blanking_sheet_link.wait_for(state="visible", timeout=30000)

        href = blanking_sheet_link.get_attribute("href")
        if not href:
            raise RuntimeError("HT View Blanking Sheet link found but href is empty.")

        blanking_url = urljoin(self.base_url, href)

        self.logger.info("Opening HT blanking sheet page: %s", blanking_url)

        self._goto_page(blanking_url)

        self.page.wait_for_function(
            """
            () => {
                return window.location.href.includes("/BlankingSheets/GenerateReport/");
            }
            """,
            timeout=30000,
        )

        self.page.locator("#ReportViewerReportFrame").wait_for(
            state="attached",
            timeout=30000,
        )

    # ------------------------------------------------------------------
    # Report extraction
    # ------------------------------------------------------------------

    def _wait_for_report_loaded(self) -> None:
        self.logger.info("Waiting for HT report iframe content to load")

        self.page.locator("#ReportViewerReportFrame").wait_for(
            state="attached",
            timeout=30000,
        )

        for _ in range(45):
            try:
                blocks = self._get_report_text_blocks()
                texts = {self._normalize_report_label(block.get("text")) for block in blocks}

                if (
                    self._normalize_report_label("Connection Data") in texts
                    and self._normalize_report_label("Pipe Body Data") in texts
                ):
                    return

            except Exception:
                pass

            self.page.wait_for_timeout(1000)

        raise RuntimeError("HT report content did not finish loading.")

    def _wait_for_blanking_report_loaded(self) -> None:
        self.logger.info("Waiting for HT blanking report iframe content to load")

        self.page.locator("#ReportViewerReportFrame").wait_for(
            state="attached",
            timeout=30000,
        )

        for _ in range(45):
            try:
                blocks = self._get_report_text_blocks()
                texts = {self._normalize_report_label(block.get("text")) for block in blocks}

                if (
                    self._normalize_report_label("ACCESSORY BLANKING DIMENSIONS") in texts
                    and self._normalize_report_label("ACCESSORY PIN") in texts
                    and self._normalize_report_label("ACCESSORY BOX") in texts
                ):
                    return

            except Exception:
                pass

            self.page.wait_for_timeout(1000)

        raise RuntimeError("HT blanking report content did not finish loading.")

    def extract_required_data(self, mapped_data: dict[str, Any]) -> dict[str, Any]:
        connection_data = self._extract_connection_data()

        drift = self.NA
        if bool(mapped_data.get("drift_extraction")):
            drift = self._extract_api_drift_diameter()

        return {
            **connection_data,
            "drift": drift,
        }

    def _extract_connection_data(self) -> dict[str, str | None]:
        return {
            "tensile": self._extract_report_number(
                section_label="Connection Data",
                field_label="Longitudinal Yield Strength",
            ),
            "compression": self._extract_report_number(
                section_label="Connection Data",
                field_label="Compressive Limit",
            ),
            "burst": self._extract_report_number(
                section_label="Connection Data",
                field_label="Internal Pressure Rating",
            ),
            "collapse": self._extract_report_number(
                section_label="Connection Data",
                field_label="External Pressure Rating",
            ),
        }

    def _extract_api_drift_diameter(self) -> str | None:
        return self._extract_report_number(
            section_label="Pipe Body Data",
            field_label="API Drift Diameter",
        )

    def extract_blanking_dimensions(self, mapped_data: dict[str, Any]) -> dict[str, Any]:
        connection = mapped_data.get("connection") or {}
        connection_type = (connection.get("type") or "").upper().strip()

        if connection_type not in self.BLANKING_COLUMNS:
            raise ValueError(
                f"HT blanking extraction only supports PIN or BOX connection type. "
                f"Got: {connection.get('type')}"
            )

        blocks = self._get_report_text_blocks()
        columns = self.BLANKING_COLUMNS[connection_type]

        od = self._extract_blanking_dimension_by_column(
            blocks=blocks,
            column_left=columns["od"],
        )
        id_value = self._extract_blanking_dimension_by_column(
            blocks=blocks,
            column_left=columns["id"],
        )

        internal_length = self._extract_min_blanking_length(
            blocks=blocks,
            column_lefts=columns["internal_length"],
        )
        external_length = self._extract_min_blanking_length(
            blocks=blocks,
            column_lefts=columns["external_length"],
        )

        self.logger.info(
            "Extracted HT blanking dimensions for %s: od=%s, id=%s, external_length=%s, internal_length=%s",
            connection_type,
            od,
            id_value,
            external_length,
            internal_length,
        )

        return {
            "od": od,
            "id": id_value,
            "external_length": external_length,
            "internal_length": internal_length,
        }

    def _extract_report_number(
        self,
        section_label: str,
        field_label: str,
    ) -> str:
        blocks = self._get_report_text_blocks()

        section_start, section_end = self._find_report_section_bounds(
            blocks=blocks,
            section_label=section_label,
        )

        label_block = self._find_report_label_block(
            blocks=blocks,
            section_start=section_start,
            section_end=section_end,
            field_label=field_label,
        )

        value_text = self._find_report_value_for_label(
            blocks=blocks,
            label_block=label_block,
            section_start=section_start,
            section_end=section_end,
        )

        number = self._extract_first_number(value_text)
        if number is None:
            raise RuntimeError(
                f"Could not extract numeric value from HT report field. "
                f"section=[{section_label}], field=[{field_label}], raw_value=[{value_text}]"
            )

        return number

    def _get_report_frame(self):
        iframe = self.page.locator("#ReportViewerReportFrame")
        iframe.wait_for(state="attached", timeout=30000)

        iframe_handle = iframe.element_handle()
        if iframe_handle is None:
            raise RuntimeError("HT ReportViewerReportFrame element handle not found.")

        frame = iframe_handle.content_frame()
        if frame is None:
            raise RuntimeError("HT ReportViewerReportFrame content frame not found.")

        return frame

    def _get_report_text_blocks(self) -> list[dict[str, Any]]:
        frame = self._get_report_frame()

        return frame.evaluate(
            """
            () => {
                const parsePx = (styleText, name) => {
                    const regex = new RegExp(name + "\\\\s*:\\\\s*(-?\\\\d+(?:\\\\.\\\\d+)?)px", "i");
                    const match = String(styleText || "").match(regex);
                    return match ? Number(match[1]) : null;
                };

                const normalize = (value) => {
                    return String(value || "")
                        .replace(/\\u00a0/g, " ")
                        .replace(/\\s+/g, " ")
                        .trim();
                };

                const nodes = Array.from(document.querySelectorAll("div[data-id]"));

                return nodes
                    .map((el) => {
                        const styleText = el.getAttribute("style") || "";
                        const text = normalize(el.innerText || el.textContent || "");

                        const left = parsePx(styleText, "left");
                        const top = parsePx(styleText, "top");
                        const width = parsePx(styleText, "width");
                        const height = parsePx(styleText, "height");

                        if (!text || left === null || top === null) {
                            return null;
                        }

                        return {
                            id: el.getAttribute("data-id") || "",
                            text,
                            left,
                            top,
                            width: width || 0,
                            height: height || 0,
                        };
                    })
                    .filter(Boolean);
            }
            """
        )

    def _find_report_section_bounds(
        self,
        blocks: list[dict[str, Any]],
        section_label: str,
    ) -> tuple[float, float]:
        target = self._normalize_report_label(section_label)

        section_blocks = [
            block
            for block in blocks
            if self._normalize_report_label(block.get("text")) == target
        ]

        if not section_blocks:
            raise RuntimeError(f"HT report section not found: {section_label}")

        section_block = min(section_blocks, key=lambda block: float(block.get("top", 0)))
        section_start = float(section_block.get("top", 0))

        all_section_labels = {
            self._normalize_report_label(label)
            for label in self.REPORT_SECTION_LABELS
        }

        next_section_tops = [
            float(block.get("top", 0))
            for block in blocks
            if (
                self._normalize_report_label(block.get("text")) in all_section_labels
                and float(block.get("top", 0)) > section_start
            )
        ]

        section_end = min(next_section_tops) if next_section_tops else float("inf")

        return section_start, section_end

    def _find_report_label_block(
        self,
        blocks: list[dict[str, Any]],
        section_start: float,
        section_end: float,
        field_label: str,
    ) -> dict[str, Any]:
        target = self._normalize_report_label(field_label)

        candidates = [
            block
            for block in blocks
            if (
                section_start <= float(block.get("top", 0)) < section_end
                and self._normalize_report_label(block.get("text")) == target
            )
        ]

        if not candidates:
            raise RuntimeError(f"HT report field label not found: {field_label}")

        return min(
            candidates,
            key=lambda block: (
                float(block.get("left", 0)),
                float(block.get("top", 0)),
            ),
        )

    def _find_report_value_for_label(
        self,
        blocks: list[dict[str, Any]],
        label_block: dict[str, Any],
        section_start: float,
        section_end: float,
    ) -> str:
        label_top = float(label_block.get("top", 0))
        label_left = float(label_block.get("left", 0))

        row_tolerance = 2.0

        candidates = [
            block
            for block in blocks
            if (
                section_start <= float(block.get("top", 0)) < section_end
                and abs(float(block.get("top", 0)) - label_top) <= row_tolerance
                and float(block.get("left", 0)) > label_left + 10
                and self._extract_first_number(block.get("text")) is not None
            )
        ]

        if not candidates:
            raise RuntimeError(
                f"HT report value not found for label: {label_block.get('text')}"
            )

        value_block = min(
            candidates,
            key=lambda block: float(block.get("left", 0)),
        )

        return str(value_block.get("text") or "").strip()

    def _extract_blanking_dimension_by_column(
        self,
        blocks: list[dict[str, Any]],
        column_left: float,
    ) -> dict[str, str]:
        tolerance_text, nominal_text = self._extract_blanking_column_tolerance_and_value(
            blocks=blocks,
            column_left=column_left,
        )

        tol_1, tol_2 = self._split_blanking_tolerance(tolerance_text)

        nominal = self._extract_first_number(nominal_text)
        if nominal is None:
            raise RuntimeError(
                f"Could not extract HT blanking nominal value. "
                f"column_left={column_left}, raw_value={nominal_text}"
            )

        return {
            "nominal": nominal,
            "tol_1": tol_1,
            "tol_2": tol_2,
        }

    def _extract_min_blanking_length(
        self,
        blocks: list[dict[str, Any]],
        column_lefts: list[float],
    ) -> str:
        values: list[float] = []

        for column_left in column_lefts:
            value_text = self._extract_blanking_column_value(
                blocks=blocks,
                column_left=column_left,
            )

            number = self._extract_first_number(value_text)
            if number is None:
                raise RuntimeError(
                    f"Could not extract HT blanking length value. "
                    f"column_left={column_left}, raw_value={value_text}"
                )

            values.append(self._to_float(number))

        if not values:
            raise RuntimeError(f"No HT blanking length values found: {column_lefts}")

        return f"{min(values):.3f}"

    def _extract_blanking_column_tolerance_and_value(
        self,
        blocks: list[dict[str, Any]],
        column_left: float,
    ) -> tuple[str, str]:
        column_blocks = self._get_blocks_by_left(
            blocks=blocks,
            column_left=column_left,
        )

        tolerance_label = self._find_column_tolerance_label_block(column_blocks)

        blocks_after_label = [
            block
            for block in column_blocks
            if float(block.get("top", 0)) > float(tolerance_label.get("top", 0))
        ]

        if len(blocks_after_label) < 2:
            raise RuntimeError(
                f"Not enough HT blanking column blocks after tolerance label. "
                f"column_left={column_left}, blocks={column_blocks}"
            )

        tolerance_block = blocks_after_label[0]
        value_block = blocks_after_label[1]

        return (
            str(tolerance_block.get("text") or "").strip(),
            str(value_block.get("text") or "").strip(),
        )

    def _extract_blanking_column_value(
        self,
        blocks: list[dict[str, Any]],
        column_left: float,
    ) -> str:
        _, value_text = self._extract_blanking_column_tolerance_and_value(
            blocks=blocks,
            column_left=column_left,
        )
        return value_text

    def _get_blocks_by_left(
        self,
        blocks: list[dict[str, Any]],
        column_left: float,
        tolerance: float = 3.0,
    ) -> list[dict[str, Any]]:
        column_blocks = [
            block
            for block in blocks
            if abs(float(block.get("left", 0)) - column_left) <= tolerance
        ]

        column_blocks = sorted(
            column_blocks,
            key=lambda block: float(block.get("top", 0)),
        )

        if not column_blocks:
            raise RuntimeError(
                f"No HT report blocks found for column_left={column_left}"
            )

        return column_blocks

    def _find_column_tolerance_label_block(
        self,
        column_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates = [
            block
            for block in column_blocks
            if self._normalize_report_label(block.get("text")) == "tolerance"
        ]

        if not candidates:
            raise RuntimeError(
                f"HT blanking tolerance label not found in column blocks: {column_blocks}"
            )

        return min(
            candidates,
            key=lambda block: float(block.get("top", 0)),
        )

    def _split_blanking_tolerance(self, tolerance_text: str) -> tuple[str, str]:
        text = str(tolerance_text or "").strip()
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", "", text)

        if not text:
            raise RuntimeError("Empty HT blanking tolerance text.")

        if text.startswith("±"):
            number = text[1:].strip()
            if not number:
                raise RuntimeError(f"Invalid HT blanking tolerance: {tolerance_text}")

            return f"+{number}", f"-{number}"

        parts = re.findall(r"[+-](?:\d+(?:\.\d+)?|\.\d+)", text)

        if len(parts) >= 2:
            return parts[0], parts[1]

        raise RuntimeError(f"Unsupported HT blanking tolerance format: {tolerance_text}")

    def _normalize_report_label(self, text: Any) -> str:
        value = str(text or "")
        value = value.replace("\u00a0", " ")
        value = re.sub(r"\s+", " ", value)
        value = value.strip().rstrip(":")
        return value.lower()

    def _extract_first_number(self, text: Any) -> str | None:
        if text is None:
            return None

        value = str(text).strip()
        if not value:
            return None

        match = re.search(r"[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)", value)
        if not match:
            return None

        return match.group(0)

    def _to_float(self, number_text: str) -> float:
        return float(str(number_text).replace(",", ""))

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _map_connection_type(self, connection_name: str) -> str:
        text = connection_name.strip().upper()
        text = text.replace(" ", "")

        if "SLHT-S" in text or "SLHTS" in text or "HT-S" in text or "HTS" in text:
            return "SEAL-LOCK HT-S"

        if "SLHT" in text or text == "HT":
            return "SEAL-LOCK HT"

        raise ValueError(f"Unsupported HT connection name: {connection_name}")

    def _map_material_grade(self, mapped_data: dict[str, Any]) -> str | None:
        connection = mapped_data.get("connection") or {}

        material_family = connection.get("material_family")
        yield_strength = connection.get("yield_strength")

        if not material_family or not yield_strength:
            return None

        return self._build_material_grade(
            material_family=str(material_family),
            yield_strength=str(yield_strength),
        )

    def _build_material_grade(
        self,
        material_family: str,
        yield_strength: str,
    ) -> str:
        family = material_family.strip().upper()
        strength = yield_strength.strip().upper()

        if strength.endswith(".0"):
            strength = strength[:-2]

        return f"{family}-{strength}"
