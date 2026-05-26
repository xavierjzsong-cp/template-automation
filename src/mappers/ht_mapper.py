from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from src.mappers.base_mapper import BaseMapper


class HtMapper(BaseMapper):

    def build_mapped_data(
        self,
        target: dict[str, Any],
        shared_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        partner = (target.get("partner") or "").upper()
        if partner != "HT":
            raise ValueError(f"HtMapper received non-HT target: {target.get('partner')}")

        shared_data = shared_data or {}
        product_material_grade = shared_data.get("product_material_grade")
        connection = target.get("connection") or {}

        return {
            "partner": "HT",
            "side": target.get("side"),
            "drift_extraction": bool(shared_data.get("drift_extraction")),
            "connection": {
                "name": self._map_connection_name(connection.get("name")),
                "od": self._map_od(connection.get("od")),
                "weight": self._map_weight(connection.get("weight")),
                "material_family": self._map_material_family(product_material_grade),
                "yield_strength": self._map_yield_strength(product_material_grade),
                "type": connection.get("type"),
            },
        }

    def _map_connection_name(self, name: str | None) -> str | None:
        if not name:
            return None

        text = name.strip().upper()
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _map_od(self, od: str | None) -> str | None:
        value = self._parse_decimal_or_fraction(od)
        if value is None:
            return od.strip() if od else None

        return self._format_decimal_3(value)

    def _map_weight(self, weight: str | None) -> str | None:
        value = self._parse_decimal_or_fraction(weight)
        if value is None:
            return weight.strip() if weight else None

        return self._format_decimal_3(value)

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

    def _parse_product_material_grade(
        self,
        product_material_grade: str | None,
    ) -> dict[str, str] | None:
        if not product_material_grade:
            return None

        text = product_material_grade.strip().upper()
        text = text.replace(" ", "")

        match = re.match(
            r"^(?P<family>[A-Z0-9]+)\((?P<strength>\d+(?:\.\d+)?)\)$",
            text,
        )

        if not match:
            return None

        return {
            "material_family": match.group("family"),
            "yield_strength": self._normalize_strength(match.group("strength")),
        }

    def _normalize_strength(self, strength: str) -> str:
        text = strength.strip()

        if text.endswith(".0"):
            text = text[:-2]

        return text

    def _parse_decimal_or_fraction(self, value: str | None) -> Decimal | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        text = text.replace('"', "")
        text = text.replace("#", "")
        text = re.sub(r"\bin\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\blb/ft\b", "", text, flags=re.IGNORECASE)
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