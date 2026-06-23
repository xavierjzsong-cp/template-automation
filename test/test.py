from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mappers.ht_mapper import HtMapper
from src.mappers.jfe_mapper import JfeMapper
from src.mappers.tsh_mapper import TshMapper
from src.mappers.vam_mapper import VamMapper
from src.parsers.pots_doc_parser import POTSDocParser
from src.routers.partner_router import PartnerRouter
from src.utils.app_paths import configure_playwright_browsers

from test.adapter_playground.common import (
    PlaywrightAdapterTestBase,
    extract_first_number,
    normalize_text,
)
from test.adapter_playground.ht_adapter_test import HtAdapter
from test.adapter_playground.jfe_adapter_test import JfeAdapter
from test.adapter_playground.tsh_adapter_test import TshAdapter
from test.adapter_playground.vam_adapter_test import VamAdapter


TEST_LOGS_DIR = PROJECT_ROOT / "test" / "logs"


REQUIRED_ADAPTER_FIELDS = [
    "tensile",
    "compression",
    "burst",
    "collapse",
    "drift",
    "od",
    "id",
    "external_length",
    "internal_length",
]


class AdapterLiveTest:
    partner: str

    def build_mapped_data(self) -> dict[str, Any]:
        raise NotImplementedError

    def build_adapter(self, partners_config: dict[str, Any], show_browser: bool):
        raise NotImplementedError

    def run(self, partners_config: dict[str, Any], show_browser: bool) -> dict[str, Any]:
        mapped_data = self.build_mapped_data()
        adapter = self.build_adapter(
            partners_config=partners_config,
            show_browser=show_browser,
        )

        try:
            result = adapter.run(mapped_data)
        finally:
            adapter.close()

        validate_adapter_result(self.partner, result)
        return result


class VamAdapterLiveTest(AdapterLiveTest):
    partner = "VAM"

    def build_mapped_data(self) -> dict[str, Any]:
        return build_vam_tsh_mapped_cases()["VAM"]

    def build_adapter(self, partners_config: dict[str, Any], show_browser: bool) -> VamAdapter:
        cfg = get_partner_config(partners_config, self.partner)
        urls = cfg["urls"]
        return VamAdapter(
            base_url=urls["homepage"],
            configurator_url=urls["connection_datasheet"],
            logs_dir=TEST_LOGS_DIR,
            headless=not show_browser,
            slow_mo=300,
            timeout_ms=10000,
        )


class TshAdapterLiveTest(AdapterLiveTest):
    partner = "TSH"

    def build_mapped_data(self) -> dict[str, Any]:
        return build_vam_tsh_mapped_cases()["TSH"]

    def build_adapter(self, partners_config: dict[str, Any], show_browser: bool) -> TshAdapter:
        cfg = get_partner_config(partners_config, self.partner)
        urls = cfg["urls"]
        return TshAdapter(
            base_url=urls["homepage"],
            datasheet_url=urls["connection_datasheet"],
            blanking_url=urls["blanking_dimensions"],
            logs_dir=TEST_LOGS_DIR,
            headless=not show_browser,
            slow_mo=300,
            timeout_ms=10000,
            navigation_timeout_ms=60000,
        )


class JfeAdapterLiveTest(AdapterLiveTest):
    partner = "JFE"

    def build_mapped_data(self) -> dict[str, Any]:
        target = {
            "partner": "JFE",
            "side": "upper",
            "connection": {
                "name": "JFEBEAR",
                "od": "4.5",
                "weight": "11.6",
                "type": "BOX",
            },
        }
        shared_data = {
            "product_material_grade": "JFE-13CR-95",
            "drift_extraction": False,
        }
        return JfeMapper().build_mapped_data(
            target=target,
            shared_data=shared_data,
        )

    def build_adapter(self, partners_config: dict[str, Any], show_browser: bool) -> JfeAdapter:
        cfg = get_partner_config(partners_config, self.partner)
        urls = cfg["urls"]
        return JfeAdapter(
            base_url=urls["homepage"],
            datasheet_url=urls["connection_datasheet"],
            blanking_url=urls["blanking_dimensions"],
            logs_dir=TEST_LOGS_DIR,
            headless=not show_browser,
            slow_mo=300,
            timeout_ms=10000,
            navigation_timeout_ms=60000,
        )


class HtAdapterLiveTest(AdapterLiveTest):
    partner = "HT"

    def build_mapped_data(self) -> dict[str, Any]:
        target = {
            "partner": "HT",
            "side": "lower",
            "connection": {
                "name": "SLHT",
                "od": "5.5",
                "weight": "20",
                "type": "PIN",
            },
        }
        shared_data = {
            "product_material_grade": "S13CR(95)",
            "drift_extraction": True,
        }
        return HtMapper().build_mapped_data(
            target=target,
            shared_data=shared_data,
        )

    def build_adapter(self, partners_config: dict[str, Any], show_browser: bool) -> HtAdapter:
        cfg = get_partner_config(partners_config, self.partner)
        urls = cfg["urls"]
        return HtAdapter(
            base_url="https://datasheet.hunting-intl.com",
            datasheet_url=urls["connection_datasheet"],
            logs_dir=TEST_LOGS_DIR,
            headless=not show_browser,
            slow_mo=300,
            timeout_ms=10000,
            navigation_timeout_ms=60000,
        )


def build_vam_tsh_mapped_cases() -> dict[str, dict[str, Any]]:
    sample_pdf = PROJECT_ROOT / "input_doc" / "POTS 10007380 Rev. A.pdf"
    if not sample_pdf.exists():
        raise FileNotFoundError(
            "VAM/TSH live tests need the local sample PDF: "
            f"{sample_pdf}"
        )

    parsed = POTSDocParser().parse(sample_pdf)
    routing_result = PartnerRouter().route(parsed)
    shared_data = routing_result.get("shared_data") or {}

    mapper_registry = {
        "VAM": VamMapper(),
        "TSH": TshMapper(),
    }

    cases: dict[str, dict[str, Any]] = {}
    for target in routing_result.get("targets") or []:
        partner = str(target.get("partner") or "").upper()
        mapper = mapper_registry.get(partner)
        if mapper is None:
            continue

        cases[partner] = mapper.build_mapped_data(
            target=target,
            shared_data=shared_data,
        )

    missing = [partner for partner in ("VAM", "TSH") if partner not in cases]
    if missing:
        raise RuntimeError(f"Sample PDF did not produce mapped cases for: {missing}")

    return cases


def load_partners_config() -> dict[str, Any]:
    config_path = PROJECT_ROOT / "config" / "partners.yaml"
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid partners config: {config_path}")

    return data


def get_partner_config(partners_config: dict[str, Any], partner: str) -> dict[str, Any]:
    partners = partners_config.get("partners") or {}
    cfg = partners.get(partner)
    if not isinstance(cfg, dict):
        raise KeyError(f"Partner config not found: {partner}")
    return cfg


def validate_adapter_result(partner: str, result: dict[str, Any]) -> None:
    missing = [
        field
        for field in REQUIRED_ADAPTER_FIELDS
        if field not in result
    ]
    if missing:
        raise AssertionError(f"{partner} adapter result missing fields: {missing}")


def run_smoke_tests() -> None:
    assert issubclass(VamAdapter, PlaywrightAdapterTestBase)
    assert issubclass(TshAdapter, PlaywrightAdapterTestBase)
    assert issubclass(JfeAdapter, PlaywrightAdapterTestBase)
    assert issubclass(HtAdapter, PlaywrightAdapterTestBase)
    assert normalize_text(" A\u00a0  B ") == "A B"
    assert extract_first_number("OD 5.500 in") == "5.500"
    print("adapter playground smoke tests passed")


def run_live_tests(show_browser: bool, selected_partners: set[str] | None = None) -> None:
    configure_playwright_browsers()
    partners_config = load_partners_config()

    tests: list[AdapterLiveTest] = [
        VamAdapterLiveTest(),
        TshAdapterLiveTest(),
        JfeAdapterLiveTest(),
        HtAdapterLiveTest(),
    ]

    for test_case in tests:
        if selected_partners and test_case.partner not in selected_partners:
            continue

        print(f"\n=== Running {test_case.partner} adapter playground test ===")
        result = test_case.run(
            partners_config=partners_config,
            show_browser=show_browser,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adapter refactor playground tests. Source adapters are not modified.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run real browser automation against partner websites.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show Playwright browser windows during live tests.",
    )
    parser.add_argument(
        "--partners",
        nargs="+",
        choices=["VAM", "TSH", "JFE", "HT"],
        help="Optional partner subset for live tests, for example: --partners JFE HT",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_smoke_tests()

    if args.live:
        selected_partners = (
            {partner.upper() for partner in args.partners}
            if args.partners
            else None
        )
        run_live_tests(
            show_browser=args.show_browser,
            selected_partners=selected_partners,
        )
    else:
        print("live adapter tests skipped; pass --live to run website automation")


if __name__ == "__main__":
    main()
