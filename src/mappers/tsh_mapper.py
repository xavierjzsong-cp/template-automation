from __future__ import annotations

import re
from typing import Any

from src.mappers.base_mapper import BaseMapper


class TshMapper(BaseMapper):
    def build_mapped_data(
        self,
        target: dict[str, Any],
        shared_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        partner = (target.get("partner") or "").upper()
        if partner != "TSH":
            raise ValueError(f"TshMapper received non-TSH target: {target.get('partner')}")

        shared_data = shared_data or {}
        product_material_grade = shared_data.get("product_material_grade")
        connection = target.get("connection") or {}

        return {
            "partner": "TSH",
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

        text = name.strip()
        if text.upper().startswith("TSH "):
            text = text[4:].strip()

        return text

    def _map_od(self, od: str | None) -> str | None:
        if not od:
            return None

        try:
            return f"{float(od):.3f}"
        except ValueError:
            return od.strip()

    def _map_weight(self, weight: str | None) -> str | None:
        if not weight:
            return None

        try:
            return f"{float(weight):.2f}"
        except ValueError:
            return weight.strip()
    
    def _map_material_family(self, grade: str | None) -> str | None:
        if not grade:
            return None

        text = grade.strip().upper()
        match = re.match(r"^([A-Z0-9]+)\s*[\(\[]", text)
        if match:
            return match.group(1)

        match = re.match(r"^([A-Z0-9]+)", text)
        if match:
            return match.group(1)

        return None

    def _map_yield_strength(self, grade: str | None) -> str | None:
        if not grade:
            return None

        match = re.search(r"[\(\[](\d+(?:\.\d+)?)[\)\]]", grade)
        if not match:
            return None

        value = match.group(1)
        if value.endswith(".0"):
            value = value[:-2]

        return value