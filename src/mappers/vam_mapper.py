from __future__ import annotations

import re
from typing import Any

from src.mappers.base_mapper import BaseMapper
from src.mappers.mapper_tables.vam_od_map import VAM_OD_MAP


class VamMapper(BaseMapper):

    def build_mapped_data(
        self,
        target: dict[str, Any],
        shared_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        partner = (target.get("partner") or "").upper()
        if partner != "VAM":
            raise ValueError(f"VamMapper received non-VAM target: {target.get('partner')}")

        shared_data = shared_data or {}
        product_material_grade = shared_data.get("product_material_grade")

        connection = target.get("connection") or {}

        return {
            "partner": "VAM",
            "side": target.get("side"),
            "drift_extraction": bool(shared_data.get("drift_extraction")),
            "connection": {
                "name": connection.get("name"),
                "od": self._map_od(connection.get("od")),
                "weight": self._map_weight(connection.get("weight")),
                "material_family": self._map_material_family(product_material_grade),
                "yield_strength": self._map_yield_strength(product_material_grade),
                "type": connection.get("type"),
            },
        }

    def _map_material_family(self, grade: str | None) -> str | None:
        parsed = self._parse_product_material_grade(grade)
        if parsed is None:
            return None

        return parsed["material_family"]

    def _map_yield_strength(self, grade: str | None) -> str | None:
        parsed = self._parse_product_material_grade(grade)
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
        text = re.sub(r"\s+", "", text)

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
        value = strength.strip()

        if value.endswith(".0"):
            value = value[:-2]

        return value

    def _map_od(self, od: str | None) -> str | None:
        key = self._normalize_od_key(od)
        if not key:
            return None

        return VAM_OD_MAP.get(key, od)

    def _map_weight(self, weight: str | None) -> str | None:
        if not weight:
            return None

        try:
            return f"{float(weight):.2f}"
        except ValueError:
            return weight.strip()

    def _normalize_od_key(self, od: str | None) -> str | None:
        if not od:
            return None

        text = od.strip()

        try:
            num = float(text)
        except ValueError:
            return text

        return f"{num:.6f}".rstrip("0").rstrip(".")