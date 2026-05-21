from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from src.mappers.base_mapper import BaseMapper


class JfeMapper(BaseMapper):

    FRICTION = "API Modified"
    COUPLING = "STD"

    CONNECTION_NAMES_WITHOUT_JFE_PREFIX = {
        "FOX": "FOX",
        "PLAIN END": "Plain End",
    }

    def build_mapped_data(
        self,
        target: dict[str, Any],
        shared_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        partner = (target.get("partner") or "").upper()
        if partner != "JFE":
            raise ValueError(f"JfeMapper received non-JFE target: {target.get('partner')}")

        shared_data = shared_data or {}
        connection = target.get("connection") or {}

        product_material_grade = shared_data.get("product_material_grade")

        return {
            "partner": "JFE",
            "side": target.get("side"),
            "drift_extraction": bool(shared_data.get("drift_extraction")),
            "connection": {
                "name": self._map_connection_name(connection.get("name")),
                "od": self._map_od(connection.get("od")),
                "weight": self._map_weight(connection.get("weight")),
                "material_family": self._map_material_family(product_material_grade),
                "yield_strength": self._map_yield_strength(product_material_grade),
                "grade_source": self._map_grade_source(product_material_grade),
                "friction": self.FRICTION,
                "coupling": self.COUPLING,
                "type": connection.get("type"),
            },
        }

    def _map_connection_name(self, name: str | None) -> str | None:
        if not name:
            return None

        text = name.strip()
        text = re.sub(r"\s+", " ", text).strip()
        normalized = text.upper()

        if normalized in self.CONNECTION_NAMES_WITHOUT_JFE_PREFIX:
            return self.CONNECTION_NAMES_WITHOUT_JFE_PREFIX[normalized]

        if normalized.startswith("JFE "):
            normalized = "JFE" + normalized[4:].strip()

        if normalized.startswith("JFE"):
            return normalized

        return f"JFE{normalized}"

    def _map_od(self, od: str | None) -> str | None:
        value = self._parse_decimal_or_fraction(od)
        if value is None:
            return od.strip() if od else None

        return self._format_decimal_3(value)

    def _map_weight(self, weight: str | None) -> str | None:
        value = self._parse_decimal_or_fraction(weight)
        if value is None:
            return weight.strip() if weight else None

        return self._format_compact_decimal(value)

    def _map_material_family(self, product_material_grade: str | None) -> str | None:
        parsed = self._parse_product_material_grade(product_material_grade)
        if parsed is None:
            return None

        return parsed["material_family"]

    def _map_yield_strength(self, product_material_grade: str | None) -> str | None:
        parsed = self._parse_product_material_grade(product_material_grade)
        if parsed is None:
            return None

        return parsed["yield_strength"]

    def _map_grade_source(self, product_material_grade: str | None) -> str:
        """
        根据 router 传入的 product_material_grade 判断。
        如果未来 parser 识别到 JFE 自有 grade，应在 product_material_grade 中保留 JFE 信息。
        """
        if not product_material_grade:
            return "standard"

        text = product_material_grade.strip().upper()

        if re.search(r"\bJFE\b", text) or text.startswith("JFE"):
            return "jfe"

        return "standard"

    def _parse_product_material_grade(
        self,
        product_material_grade: str | None,
    ) -> dict[str, str] | None:
        if not product_material_grade:
            return None

        text = product_material_grade.strip().upper()
        text = text.replace(" ", "")

        patterns = [
            r"^(?P<family>[A-Z0-9]+)\((?P<strength>\d+(?:\.\d+)?)\)$",

            # 预留：JFE 自有 grade，当前先只支持 13CR
            r"^JFE[-]?(?P<family>13CR)[-]?(?P<strength>\d+(?:\.\d+)?)$",
        ]

        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                material_family = match.group("family")
                yield_strength = match.group("strength")

                return {
                    "material_family": material_family,
                    "yield_strength": self._normalize_strength(yield_strength),
                }

        return None

    def _normalize_strength(self, strength: str) -> str:
        value = strength.strip()

        if value.endswith(".0"):
            value = value[:-2]

        return value

    def _parse_decimal_or_fraction(self, value: str | None) -> Decimal | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        text = text.replace('"', "")
        text = text.replace("#", "")
        text = re.sub(r"\bIN\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bLB/FT\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()

        fraction_match = re.match(
            r"^(?P<whole>\d+(?:\.\d+)?)\s+(?P<num>\d+)/(?P<den>\d+)$",
            text,
        )

        if fraction_match:
            whole = Decimal(fraction_match.group("whole"))
            numerator = Decimal(fraction_match.group("num"))
            denominator = Decimal(fraction_match.group("den"))

            if denominator == 0:
                return None

            return whole + numerator / denominator

        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    def _format_decimal_3(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.001')):.3f}"

    def _format_compact_decimal(self, value: Decimal) -> str:
        if value == value.to_integral_value():
            return str(int(value))

        text = format(value.normalize(), "f")
        return text.rstrip("0").rstrip(".")