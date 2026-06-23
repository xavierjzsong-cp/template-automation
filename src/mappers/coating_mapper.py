from __future__ import annotations

import re
from typing import Any

from src.mappers.mapper_tables.coating_map import COATING_MAP


class CoatingMapper:

    PREMIUM_THREAD_PARTNERS = {
        "VAM",
        "TSH",
        "JFE",
        "HT",
    }

    def build_mapped_data(self, router_output: dict[str, Any]) -> dict[str, str | None]:
        shared_data = router_output.get("shared_data") or {}
        product_material_grade = shared_data.get("product_material_grade")

        material_category = self.map_material_category(product_material_grade)

        top_partner, bottom_partner = self._extract_top_bottom_partners(router_output)

        top_feature = self.map_thread_feature(top_partner)
        bottom_feature = self.map_thread_feature(bottom_partner)

        return {
            "top_thread_coating": self.map_coating_by_feature(
                feature=top_feature,
                material_category=material_category,
            ),
            "bottom_thread_coating": self.map_coating_by_feature(
                feature=bottom_feature,
                material_category=material_category,
            ),
            "body_coating": self.map_coating_by_feature(
                feature="base_coating",
                material_category=material_category,
            ),
        }

    def map_thread_feature(self, partner: str | None) -> str | None:
        if not partner:
            return None

        partner_key = partner.strip().upper()

        if partner_key in self.PREMIUM_THREAD_PARTNERS:
            return "premium_threads"

        return None

    def map_coating_by_feature(
        self,
        feature: str | None,
        material_category: str | None,
    ) -> str | None:
        if not feature or not material_category:
            return None

        feature_map = COATING_MAP.get(feature)
        if not feature_map:
            raise ValueError(f"Unsupported coating feature: {feature}")

        coating = feature_map.get(material_category)
        if coating is None:
            raise ValueError(
                f"Coating not found for feature={feature}, "
                f"material_category={material_category}"
            )

        return coating

    def map_material_category(self, product_material_grade: str | None) -> str | None:

        compact = self._normalize_material_compact(product_material_grade)

        if not compact:
            return None

        if "CR" in compact:
            return "chrome_steel"

        if "INCOLLOY" in compact or "INCOL" in compact:
            return "nickel_alloy"

        if re.search(r"41\d{2}", compact):
            return "alloy_steel"

        return None

    def _extract_top_bottom_partners(
        self,
        router_output: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        targets = router_output.get("targets") or []

        top_partner = None
        bottom_partner = None

        for target in targets:
            if not isinstance(target, dict):
                continue

            side = str(target.get("side") or "").strip().lower()
            partner = target.get("partner")

            if not partner:
                continue

            if side == "upper":
                top_partner = str(partner)
            elif side == "lower":
                bottom_partner = str(partner)

        return top_partner, bottom_partner

    def _normalize_material_compact(self, material: str | None) -> str:
        if not material:
            return ""

        text = str(material).upper()
        text = text.replace("（", "(").replace("）", ")")
        text = re.sub(r"[^A-Z0-9]+", "", text)

        return text
