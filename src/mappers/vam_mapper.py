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
                #"material_family": self._map_material_family(product_material_grade),
                "yield_strength": self._map_yield_strength(product_material_grade),
                "type": connection.get("type"),
            },
        }

    # 也可以做成映射表
    # def _map_material_family(self, grade: str | None) -> str | None:
    #     if not grade:
    #         return None
    #
    #     g = grade.upper().replace("[", "(").replace("]", ")").strip()
    #
    #     # if g in {"N/A", "NA"}:
    #     #     return "N/A"
    #
    #     # if "DEEP WELL" in g:
    #     #     return "Deep well"
    #
    #     if g.startswith("13CR"):
    #         return "13% Chromium (13Cr)"
    #
    #     if g.startswith("S13CR") or g.startswith("SUPER 13"):
    #         return "Super 13% Chromium (S13Cr)"
    #
    #     # if g in {"L80", "P110", "C90", "T95"} or "CARBON" in g:
    #     #     return "Carbon Steel"
    #
    #     if "CRA" in g:
    #         return "Corrosion Resistant Alloy (CRA)"
    #
    #     return None

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