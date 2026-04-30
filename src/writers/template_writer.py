from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell


class TemplateWriter:

    DEFAULT_ANGLE = 30
    NA = "NA"

    def write(
        self,
        parsed: dict[str, Any],
        top_adapter: dict[str, Any] | None,
        bottom_adapter: dict[str, Any] | None,
        template_path: str | Path,
        output_dir: str | Path = "output_docs",
    ) -> dict[str, Any]:
        formatted = self._build_template_fields(
            parsed=parsed,
            top_adapter=top_adapter,
            bottom_adapter=bottom_adapter,
        )

        print("\n=== Formatted Data ===")
        print(formatted)

        output_file = self._write_to_template(
            template_path=template_path,
            formatted=formatted,
            output_dir=output_dir,
        )

        print(f"\nSaved output file: {output_file}")

        return {
            "parsed": parsed,
            "formatted": formatted,
            "output_file": str(output_file),
        }

    def _build_template_fields(
        self,
        parsed: dict[str, Any],
        top_adapter: dict[str, Any] | None,
        bottom_adapter: dict[str, Any] | None,
    ) -> dict[str, Any]:
        connections = parsed.get("connections") or {}
        upper = connections.get("upper") or {}
        lower = connections.get("lower") or {}

        top_thread_text = self._format_thread(
            od=upper.get("od"),
            weight=upper.get("weight"),
            connection_name=upper.get("name"),
        )

        bottom_thread_text = self._format_thread(
            od=lower.get("od"),
            weight=lower.get("weight"),
            connection_name=lower.get("name"),
        )

        material = self._format_material(
            mds=parsed.get("ansi_nace"),
            grade=parsed.get("product_material_grade"),
        )

        formatted_description = self._format_description(
            top_thread=top_thread_text,
            bottom_thread=bottom_thread_text,
            material=material,
        )

        return {
            "part_number": parsed.get("part_number"),
            "rev": parsed.get("rev"),
            "qcp": self._format_qcp(parsed.get("qcp")),
            "product_type": parsed.get("product_type"),
            "description": formatted_description,
            "material": material,
            "overall_length": self._format_overall_length(parsed.get("overall_length")),
            "top_thread": {
                "thread": top_thread_text,
                **(top_adapter or {}),
            },
            "bottom_thread": {
                "thread": bottom_thread_text,
                **(bottom_adapter or {}),
            },
        }

    def _format_thread(
        self,
        od: str | None,
        weight: str | None,
        connection_name: str | None,
    ) -> str | None:
        if not od or not weight or not connection_name:
            return None

        normalized_name = self._normalize_connection_name(connection_name)
        return f"{od} - {weight}# {normalized_name}"

    def _normalize_connection_name(self, connection_name: str) -> str:
        text = connection_name.strip()
        text = re.sub(r"\bWEDGE\s+511\b", "W511", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _format_material(self, mds: str | None, grade: str | None) -> str | None:
        if not mds and not grade:
            return None

        normalized_grade = self._normalize_grade(grade) if grade else None

        if mds and normalized_grade:
            return f"{mds} ({normalized_grade})"
        if mds:
            return mds
        return normalized_grade

    def _normalize_grade(self, grade: str) -> str:
        grade = grade.strip()

        match = re.match(r"^([A-Za-z0-9]+)\(([\d.]+)\)$", grade)
        if match:
            material_family = match.group(1)
            strength = match.group(2)
            return f"{material_family}-{strength}KSI"

        return grade

    def _format_qcp(self, qcp: str | None) -> str | None:
        if not qcp:
            return None

        qcp = qcp.strip()
        qcp = re.sub(r"\bSTANDARD\b", "STD", qcp, flags=re.IGNORECASE)
        qcp = re.sub(r"\s+", " ", qcp).strip()
        return qcp

    def _format_description(
        self,
        top_thread: str | None,
        bottom_thread: str | None,
        material: str | None,
    ) -> str | None:
        if not top_thread and not bottom_thread and not material:
            return None

        thread_part = None
        if top_thread and bottom_thread:
            thread_part = f"{top_thread} x {bottom_thread}"
        elif top_thread:
            thread_part = top_thread
        elif bottom_thread:
            thread_part = bottom_thread

        if thread_part and material:
            return f"{thread_part}, {material}"
        if thread_part:
            return thread_part
        return material

    def _format_overall_length(self, overall_length: str | None) -> str | None:
        if not overall_length:
            return None

        match = re.search(r"(\d+(?:\.\d+)?)", overall_length)
        if not match:
            return None

        value = float(match.group(1))
        return f"{value:.3f} +/-.125"

    def _get_max_overall_length(self, formatted_overall_length: str | None) -> str | None:
        if not formatted_overall_length:
            return None

        match = re.search(
            r"(\d+(?:\.\d+)?)\s*\+/-\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))",
            formatted_overall_length,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        nominal = float(match.group(1))
        tol = float(match.group(2))
        max_value = nominal + tol
        return f"{max_value:.3f}"

    def _format_thread_dimension(self, dimension: dict[str, Any] | None) -> str | None:
        if not dimension:
            return None

        if "min" in dimension and "max" in dimension:
            return self._format_min_max_dimension(dimension)

        if "nominal" in dimension and "tol_1" in dimension and "tol_2" in dimension:
            return self._format_nominal_tolerance_dimension(dimension)

        return None

    def _format_min_max_dimension(self, dimension: dict[str, Any]) -> str | None:
        min_value = dimension.get("min")
        max_value = dimension.get("max")

        if not min_value or not max_value:
            return None

        return f"{max_value} / {min_value}"

    def _format_nominal_tolerance_dimension(self, dimension: dict[str, Any]) -> str | None:
        nominal = dimension.get("nominal")
        tol_1 = dimension.get("tol_1")
        tol_2 = dimension.get("tol_2")

        if not nominal or not tol_1 or not tol_2:
            return None

        tol_1 = str(tol_1).strip()
        tol_2 = str(tol_2).strip()

        if tol_1.startswith("+") and tol_2.startswith("-"):
            upper_tol = tol_1
            lower_tol = tol_2
        elif tol_1.startswith("-") and tol_2.startswith("+"):
            upper_tol = tol_2
            lower_tol = tol_1
        else:
            try:
                t1 = float(tol_1.replace("+", ""))
                t2 = float(tol_2.replace("+", ""))
                if t1 >= t2:
                    upper_tol = tol_1
                    lower_tol = tol_2
                else:
                    upper_tol = tol_2
                    lower_tol = tol_1
            except Exception:
                upper_tol = tol_1
                lower_tol = tol_2

        upper_tol = self._compact_positive_tol(upper_tol)

        if lower_tol.startswith("+"):
            lower_part = f"/{self._compact_positive_tol(lower_tol)}"
        else:
            lower_part = f"/ {lower_tol}"

        return f"{nominal} {upper_tol} {lower_part}"

    def _compact_positive_tol(self, tol: str | None) -> str | None:
        if not tol:
            return None

        text = str(tol).strip()
        if text.startswith("+0."):
            return "+." + text[3:]
        return text

    def _get_thread_dimension_max(self, dimension: dict[str, Any] | None) -> Decimal | None:
        if not dimension:
            return None

        if "min" in dimension and "max" in dimension:
            return self._to_decimal(dimension.get("max"))

        if "nominal" in dimension and "tol_1" in dimension and "tol_2" in dimension:
            nominal = self._to_decimal(dimension.get("nominal"))
            tol_1 = self._to_decimal(dimension.get("tol_1"))
            tol_2 = self._to_decimal(dimension.get("tol_2"))

            if nominal is None or tol_1 is None or tol_2 is None:
                return None

            return nominal + max(tol_1, tol_2)

        return None

    def _get_thread_dimension_min(self, dimension: dict[str, Any] | None) -> Decimal | None:
        if not dimension:
            return None

        if "min" in dimension and "max" in dimension:
            return self._to_decimal(dimension.get("min"))

        if "nominal" in dimension and "tol_1" in dimension and "tol_2" in dimension:
            nominal = self._to_decimal(dimension.get("nominal"))
            tol_1 = self._to_decimal(dimension.get("tol_1"))
            tol_2 = self._to_decimal(dimension.get("tol_2"))

            if nominal is None or tol_1 is None or tol_2 is None:
                return None

            return nominal + min(tol_1, tol_2)

        return None

    def _get_overall_od_max(self, formatted: dict[str, Any]) -> str | None:
        top_thread = formatted.get("top_thread") or {}
        bottom_thread = formatted.get("bottom_thread") or {}

        candidates = [
            self._get_thread_dimension_max(top_thread.get("od")),
            self._get_thread_dimension_max(bottom_thread.get("od")),
        ]

        candidates = [value for value in candidates if value is not None]
        if not candidates:
            return None

        return self._format_decimal(max(candidates))

    def _get_overall_id_min(self, formatted: dict[str, Any]) -> str | None:
        top_thread = formatted.get("top_thread") or {}
        bottom_thread = formatted.get("bottom_thread") or {}

        candidates = [
            self._get_thread_dimension_min(top_thread.get("id")),
            self._get_thread_dimension_min(bottom_thread.get("id")),
        ]

        candidates = [value for value in candidates if value is not None]
        if not candidates:
            return None

        return self._format_decimal(min(candidates))

    def _get_min_thread_metric(
        self,
        formatted: dict[str, Any],
        metric_name: str,
        suffix_k: bool = False,
    ) -> str | None:
        top_thread = formatted.get("top_thread") or {}
        bottom_thread = formatted.get("bottom_thread") or {}

        candidates: list[Decimal] = []

        top_value = self._extract_decimal_from_value(top_thread.get(metric_name))
        bottom_value = self._extract_decimal_from_value(bottom_thread.get(metric_name))

        if top_value is not None:
            candidates.append(top_value)
        if bottom_value is not None:
            candidates.append(bottom_value)

        if not candidates:
            return None

        min_value = min(candidates)

        if suffix_k:
            return f"{self._format_metric_number(min_value)}K"

        return self._format_metric_number(min_value, use_comma=True)

    def _extract_decimal_from_value(self, value: Any) -> Decimal | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
        if not match:
            return None

        return self._to_decimal(match.group(0))

    def _format_metric_number(self, value: Decimal, use_comma: bool = False) -> str:
        if value == value.to_integral_value():
            integer_value = int(value)
            if use_comma:
                return f"{integer_value:,}"
            return str(integer_value)

        normalized = value.normalize()
        text = format(normalized, "f")

        if use_comma:
            integer_part, _, decimal_part = text.partition(".")
            integer_part = f"{int(integer_part):,}"
            return f"{integer_part}.{decimal_part}" if decimal_part else integer_part

        return text

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None

        text = str(value).strip().replace(",", "")
        if not text:
            return None

        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    def _format_decimal(self, value: Decimal) -> str:
        value = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return f"{value:.3f}"

    # Template writing
    def _write_to_template(
        self,
        template_path: str | Path,
        formatted: dict[str, Any],
        output_dir: str | Path,
    ) -> Path:
        template_path = Path(template_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        workbook = load_workbook(template_path)

        # worksheet 先 hardcode，后面需补充判断逻辑
        sheet = workbook.worksheets[3]

        self._write_if_editable(sheet, "B6", formatted.get("part_number"))
        self._write_if_editable(sheet, "D6", formatted.get("rev"))
        self._write_if_editable(sheet, "B18", formatted.get("material"))
        self._write_if_editable(sheet, "B8", formatted.get("product_type"))
        self._write_if_editable(sheet, "B28", (formatted.get("top_thread") or {}).get("thread"))
        self._write_if_editable(sheet, "B30", (formatted.get("bottom_thread") or {}).get("thread"))
        self._write_if_editable(sheet, "B34", formatted.get("qcp"))
        self._write_if_editable(sheet, "H9", formatted.get("overall_length"))

        # Product overall OD max / ID min
        self._write_if_editable(
            sheet,
            "B13",
            self._get_overall_od_max(formatted),
        )
        self._write_if_editable(
            sheet,
            "B14",
            self._get_overall_id_min(formatted),
        )

        # Overall length max
        self._write_if_editable(
            sheet,
            "B15",
            self._get_max_overall_length(formatted.get("overall_length")),
        )

        # Thread performance min values
        self._write_if_editable(
            sheet,
            "B22",
            self._get_min_thread_metric(formatted, "tensile", suffix_k=True),
        )
        self._write_if_editable(
            sheet,
            "B23",
            self._get_min_thread_metric(formatted, "compression", suffix_k=True),
        )
        self._write_if_editable(
            sheet,
            "B24",
            self._get_min_thread_metric(formatted, "burst", suffix_k=False),
        )
        self._write_if_editable(
            sheet,
            "B25",
            self._get_min_thread_metric(formatted, "collapse", suffix_k=False),
        )

        # Top thread
        self._write_if_editable(
            sheet,
            "H13",
            self._format_thread_dimension((formatted.get("top_thread") or {}).get("od")),
        )
        self._write_if_editable(
            sheet,
            "H14",
            self._format_thread_dimension((formatted.get("top_thread") or {}).get("id")),
        )

        # Bottom thread
        self._write_if_editable(
            sheet,
            "H22",
            self._format_thread_dimension((formatted.get("bottom_thread") or {}).get("od")),
        )
        self._write_if_editable(
            sheet,
            "H23",
            self._format_thread_dimension((formatted.get("bottom_thread") or {}).get("id")),
        )

        self._write_if_editable(sheet, "B35", self.NA)
        self._write_if_editable(sheet, "B36", self.NA)
        self._write_if_editable(sheet, "B37", self.NA)

        self._write_if_editable(sheet, "H16", self.DEFAULT_ANGLE)
        self._write_if_editable(sheet, "H18", self.DEFAULT_ANGLE)
        self._write_if_editable(sheet, "H25", self.DEFAULT_ANGLE)
        self._write_if_editable(sheet, "H27", self.DEFAULT_ANGLE)

        part_number = formatted.get("part_number")
        if not part_number:
            raise ValueError("part_number is missing, cannot name output file.")

        output_file = output_dir / f"{part_number}.xlsx"
        workbook.save(output_file)

        return output_file

    def _write_if_editable(self, sheet, cell_ref: str, value: Any) -> None:
        if value is None:
            return

        if not self._is_cell_editable(sheet, cell_ref):
            return

        sheet[cell_ref] = value

    def _is_cell_editable(self, sheet, cell_ref: str) -> bool:
        cell = sheet[cell_ref]

        if isinstance(cell, MergedCell):
            return False

        current_value = cell.value
        if isinstance(current_value, str):
            normalized = current_value.strip().upper()
            if normalized in {"NA", "N/A"}:
                return False

        return True