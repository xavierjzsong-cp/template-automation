from __future__ import annotations

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

        connection = target.get("connection") or {}

        return {
            "partner": "TSH",
            "side": target.get("side"),
            "connection": {
                "name": self._map_connection_name(connection.get("name")),
                "od": self._map_od(connection.get("od")),
                "weight": self._map_weight(connection.get("weight")),
                "grade": self._map_grade(shared_data),
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

    def _map_grade(self, shared_data: dict[str, Any] | None) -> str:
        # 当前先 hardcode
        return "L80 Type 13Cr"