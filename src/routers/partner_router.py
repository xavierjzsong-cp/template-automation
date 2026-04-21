from __future__ import annotations

from typing import Any


class PartnerRouter:

    # routing
    def route(self, document_result: dict[str, Any]) -> dict[str, Any]:
        connections = document_result.get("connections") or {}

        targets: list[dict[str, Any]] = []

        upper = connections.get("upper")
        lower = connections.get("lower")

        upper_target = self._build_target("upper", upper)
        if upper_target:
            targets.append(upper_target)

        lower_target = self._build_target("lower", lower)
        if lower_target:
            targets.append(lower_target)

        partners_involved = self._collect_partners(targets)

        shared_data = {
            "product_material_grade": document_result.get("product_material_grade"),
            "overall_length": document_result.get("overall_length"),
        }

        return {
            "shared_data": shared_data,
            "partners_involved": partners_involved,
            "targets": targets,
        }

    # mapping
    def map_targets(
        self,
        routing_result: dict[str, Any],
        mapper_registry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        shared_data = routing_result.get("shared_data") or {}
        targets = routing_result.get("targets") or []

        mapped_results: list[dict[str, Any]] = []

        for target in targets:
            partner = (target.get("partner") or "").upper()
            if not partner:
                continue

            mapper = mapper_registry.get(partner)
            if mapper is None:
                #raise ValueError(f"No mapper registered for partner: {partner}")
                # 先跳过其他mapper 只测试vam mapper
                print(f"Skipping target because no mapper is registered for partner: {partner}")
                continue

            mapped_data = mapper.build_mapped_data(
                target=target,
                shared_data=shared_data,
            )

            mapped_results.append(mapped_data)

        return mapped_results

    def _build_target(
        self,
        side: str,
        connection: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not connection:
            return None

        partner = self._normalize_partner(connection.get("family"))
        if not partner:
            return None

        connection_name = self._strip_connection_end(connection.get("name"), connection.get("type"))

        return {
            "partner": partner,
            "side": side,
            "connection": {
                "name": connection_name,
                "od": connection.get("od"),
                "weight": connection.get("weight"),
                "type": connection.get("type"),
            },
        }

    def _normalize_partner(self, family: str | None) -> str | None:
        if not family:
            return None

        partner = family.strip().upper()
        return partner if partner else None

    def _strip_connection_end(self, name: str | None, conn_type: str | None) -> str | None:
        if not name:
            return None

        text = name.strip()
        if not conn_type:
            return text

        suffix = conn_type.strip().upper()
        upper_text = text.upper()

        if upper_text.endswith(f" {suffix}"):
            return text[: -(len(suffix) + 1)].strip()

        return text

    def _collect_partners(self, targets: list[dict[str, Any]]) -> list[str]:
        partners: list[str] = []

        for target in targets:
            partner = target.get("partner")
            if partner and partner not in partners:
                partners.append(partner)

        return partners