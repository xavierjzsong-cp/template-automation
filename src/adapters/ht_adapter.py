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

        self.logger = setup_logger(self.logs_dir, "ht_adapter_v1.0")

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
        od = connection.get("od")
        weight = connection.get("weight")

        if not connection_name or not od or not weight:
            raise ValueError(
                "HT mapped_data missing one of required fields: "
                "connection.name, connection.od, connection.weight"
            )

        connection_type = self._map_connection_type(connection_name)
        od_value = self._map_od(od)
        weight_value = self._map_weight(weight)
        material_grade = self._map_material_grade(mapped_data)

        if not material_grade:
            raise ValueError(
                "HT mapped_data missing material grade information. "
                "Expected connection.material_grade or connection.material_family + connection.yield_strength."
            )

        self.open_datasheet_page()
        self._wait_for_search_page_loaded()

        self._select_search_options(
            connection_type=connection_type,
            od_value=od_value,
            weight_value=weight_value,
            material_grade=material_grade,
        )

        self._click_filter_and_open_report()

        return {
            "status": "report_opened",
            "report_url": self.page.url,
        }

    # ------------------------------------------------------------------
    # Page open
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Page readiness
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Search selections
    # ------------------------------------------------------------------

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

        # PlainEndWeight 和 Wall 会由 Kendo cascade 自动选择。
        # MaterialGrade 依赖 Wall，所以这里等待它的数据源加载完成。
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
                        .replace(/[\\s\\-()]/g, "");
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
                    }

                    if (matchMode === "material") {
                        const optionMaterial = normalizeMaterial(optionText);
                        const targetMaterial = normalizeMaterial(target);

                        if (optionMaterial === targetMaterial) {
                            return 10000;
                        }

                        if (
                            optionMaterial.includes(targetMaterial)
                            || targetMaterial.includes(optionMaterial)
                        ) {
                            return 8000 - optionText.length;
                        }
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

                // 等待数据源加载，尤其是 cascade dropdown。
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

    # ------------------------------------------------------------------
    # Filter / report page
    # ------------------------------------------------------------------

    def _click_filter_and_open_report(self) -> None:
        self.logger.info("Clicking HT Filter button")

        filter_button = self.page.locator("#searchtable a.k-button:has-text('Filter')").first
        filter_button.wait_for(state="visible", timeout=15000)
        filter_button.click()

        try:
            self.page.wait_for_url(
                re.compile(r".*/ConnectorSheets/GenerateReport/.*"),
                timeout=10000,
            )
            return
        except PlaywrightTimeoutError:
            pass

        # 部分情况下 Filter 先显示 result grid，再需要点击 View Datasheet。
        view_datasheet = self.page.locator(
            "a[href*='/ConnectorSheets/GenerateReport/']:has-text('View Datasheet')"
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

    def _map_od(self, od: str) -> str:
        value = self._parse_fraction_or_decimal(od)
        if value is None:
            return od.strip()

        return f"{value:.3f}"

    def _map_weight(self, weight: str) -> str:
        value = self._parse_fraction_or_decimal(weight)
        if value is None:
            return weight.strip()

        return f"{value:.3f}"

    def _map_material_grade(self, mapped_data: dict[str, Any]) -> str | None:
        connection = mapped_data.get("connection") or {}

        direct_grade = (
            connection.get("material_grade")
            or mapped_data.get("material_grade")
            or mapped_data.get("product_material_grade")
        )

        if direct_grade:
            mapped = self._normalize_material_grade(str(direct_grade))
            if mapped:
                return mapped

        material_family = connection.get("material_family") or mapped_data.get("material_family")
        yield_strength = connection.get("yield_strength") or mapped_data.get("yield_strength")

        if material_family and yield_strength:
            return self._build_material_grade(
                material_family=str(material_family),
                yield_strength=str(yield_strength),
            )

        return None

    def _normalize_material_grade(self, grade: str) -> str | None:
        text = grade.strip().upper()
        text = text.replace(" ", "")

        match = re.match(r"^([A-Z0-9]+)\((\d+(?:\.\d+)?)\)$", text)
        if match:
            return self._build_material_grade(
                material_family=match.group(1),
                yield_strength=match.group(2),
            )

        match = re.match(r"^([A-Z0-9]+)-(\d+(?:\.\d+)?)$", text)
        if match:
            return self._build_material_grade(
                material_family=match.group(1),
                yield_strength=match.group(2),
            )

        match = re.match(r"^(13CR)(\d+(?:\.\d+)?)$", text)
        if match:
            return self._build_material_grade(
                material_family=match.group(1),
                yield_strength=match.group(2),
            )

        if re.match(r"^[A-Z]+-\d+(?:\.\d+)?$", text):
            return text

        return grade.strip()

    def _build_material_grade(
        self,
        material_family: str,
        yield_strength: str,
    ) -> str:
        family = material_family.strip().upper()
        strength = yield_strength.strip().upper()

        if strength.endswith(".0"):
            strength = strength[:-2]

        if family == "13CR":
            return f"13-CR-{strength}"

        return f"{family}-{strength}"

    def _parse_fraction_or_decimal(self, value: str) -> float | None:
        text = str(value).strip()
        text = text.replace('"', "")
        text = text.replace("in", "")
        text = text.replace("IN", "")
        text = re.sub(r"\s+", " ", text).strip()

        fraction_match = re.match(
            r"^(\d+(?:\.\d+)?)\s+(\d+)/(\d+)$",
            text,
        )

        if fraction_match:
            whole = float(fraction_match.group(1))
            numerator = float(fraction_match.group(2))
            denominator = float(fraction_match.group(3))
            return whole + numerator / denominator

        try:
            return float(text)
        except ValueError:
            return None