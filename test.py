from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from openpyxl import load_workbook

from src.config_loader import load_partners_config, get_partner_config
from src.document_parser import DocumentParser
from src.routers.partner_router import PartnerRouter
from src.mappers.vam_mapper import VamMapper
from src.adapters.vam_adapter import VamAdapter
from src.mappers.tsh_mapper import TshMapper
from src.adapters.tsh_adapter import TshAdapter
from src.writers.template_writer import TemplateWriter
from src.adapters.jfe_adapter import JfeAdapter


"""
# 测试整个流程
def load_partners_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"partners.yaml not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid partners.yaml structure: {config_path}")

    return data


def get_partner_config(partners_config: dict[str, Any], partner: str) -> dict[str, Any]:
    partner = partner.upper()

    if "partners" in partners_config and isinstance(partners_config["partners"], dict):
        cfg = partners_config["partners"].get(partner)
        if cfg:
            return cfg

    cfg = partners_config.get(partner)
    if cfg:
        return cfg

    raise KeyError(f"Partner config not found for partner: {partner}")


def run_adapter_for_target(
    partner: str,
    side: str,
    mapped_result: dict[str, Any],
    partners_config: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    partner_cfg = get_partner_config(partners_config, partner)
    urls = partner_cfg.get("urls") or {}

    base_url = urls.get("homepage")
    if not base_url:
        raise ValueError(f"{partner} config missing urls.homepage")

    if partner == "VAM":
        configurator_url = urls.get("connection_datasheet")
        if not configurator_url:
            raise ValueError("VAM config missing urls.connection_datasheet")

        adapter = VamAdapter(
            base_url=base_url,
            configurator_url=configurator_url,
            logs_dir=project_root / "logs",
            headless=False,
            slow_mo=300,
            timeout_ms=10000,
        )

    elif partner == "TSH":
        datasheet_url = urls.get("connection_datasheet")
        blanking_url = urls.get("blanking_dimensions")

        if not datasheet_url:
            raise ValueError("TSH config missing urls.connection_datasheet")
        if not blanking_url:
            raise ValueError("TSH config missing urls.blanking_dimensions")

        adapter = TshAdapter(
            base_url=base_url,
            datasheet_url=datasheet_url,
            blanking_url=blanking_url,
            logs_dir=project_root / "logs",
            headless=False,
            slow_mo=300,
            timeout_ms=10000,
            navigation_timeout_ms=60000,
        )

    else:
        raise ValueError(f"Unsupported partner adapter: {partner}")

    try:
        adapter_result = adapter.run(mapped_result)
    finally:
        adapter.close()

    print(f"\n=== Adapter Result ({partner} / {side}) ===")
    print(adapter_result)

    validate_adapter_result(partner, side, adapter_result)

    return adapter_result


def validate_adapter_result(
    partner: str,
    side: str,
    adapter_result: dict[str, Any],
) -> None:
    required_keys = {
        "tensile",
        "compression",
        "burst",
        "collapse",
        "od",
        "id",
        "external_length",
        "internal_length",
        "drift",
    }

    missing = required_keys - set(adapter_result.keys())
    if missing:
        raise AssertionError(
            f"Adapter result missing keys for {partner}/{side}: {sorted(missing)}"
        )

    if not isinstance(adapter_result.get("od"), dict):
        raise AssertionError(f"{partner}/{side} od should be dict")

    if not isinstance(adapter_result.get("id"), dict):
        raise AssertionError(f"{partner}/{side} id should be dict")

    print(f"{partner}/{side} adapter result validation passed.")


def inspect_written_template(output_file: Path) -> None:
    if not output_file.exists():
        raise FileNotFoundError(f"Output file was not created: {output_file}")

    workbook = load_workbook(output_file, data_only=False)
    sheet = workbook.worksheets[3]

    cells_to_check = [
        "B6", "D6", "B8", "B13", "B14", "B15", "B18",
        "B22", "B23", "B24", "B25", "B28", "B30", "B33", "B34",
        "B35", "B36", "B37",
        "H9", "H13", "H14", "H15", "H16", "H17", "H18",
        "H22", "H23", "H24", "H25", "H26", "H27",
    ]

    print("\n=== Written Template Cell Values ===")
    for cell in cells_to_check:
        print(f"{cell}: {sheet[cell].value}")

    workbook.close()


def main() -> None:
    project_root = Path(__file__).resolve().parent

    input_path = project_root / "input_docs" / "POTS 10007380 Rev. A.pdf"
    template_path = project_root / "templates" / "Template_ACCESSORY (Premium) 1.xlsx"
    partners_config_path = project_root / "config" / "partners.yaml"
    output_dir = project_root / "output_docs"

    partners_config = load_partners_config(partners_config_path)

    parser = DocumentParser()
    router = PartnerRouter()
    writer = TemplateWriter()

    mapper_registry = {
        "VAM": VamMapper(),
        "TSH": TshMapper(),
    }

    parsed = parser.parse_docs(input_path)
    routing_result = router.route(parsed)

    print("=== Parsed ===")
    for k, v in parsed.items():
        if k != "raw_text":
            print(f"{k}: {v}")

    print("\n=== Routing Result ===")
    print(routing_result)

    top_adapter_result = None
    bottom_adapter_result = None

    for target in routing_result.get("targets", []):
        partner = (target.get("partner") or "").upper()
        side = target.get("side")

        mapper = mapper_registry.get(partner)
        if mapper is None:
            print(f"Skipping target because no mapper is registered for partner: {partner}")
            continue

        mapped_result = mapper.build_mapped_data(
            target=target,
            shared_data=routing_result.get("shared_data"),
        )

        print(f"\n=== Mapped Result ({partner} / {side}) ===")
        print(mapped_result)

        adapter_result = run_adapter_for_target(
            partner=partner,
            side=side,
            mapped_result=mapped_result,
            partners_config=partners_config,
            project_root=project_root,
        )

        if side == "upper":
            top_adapter_result = adapter_result
        elif side == "lower":
            bottom_adapter_result = adapter_result
        else:
            raise ValueError(f"Unsupported side: {side}")

    if top_adapter_result is None:
        raise AssertionError("top_adapter_result is None")

    if bottom_adapter_result is None:
        raise AssertionError("bottom_adapter_result is None")

    print("\n=== Top Adapter Data ===")
    print(top_adapter_result)

    print("\n=== Bottom Adapter Data ===")
    print(bottom_adapter_result)

    write_result = writer.write(
        parsed=parsed,
        top_adapter=top_adapter_result,
        bottom_adapter=bottom_adapter_result,
        template_path=template_path,
        output_dir=output_dir,
    )

    print("\n=== Writer Result ===")
    print(write_result)

    output_file = Path(write_result["output_file"])
    inspect_written_template(output_file)

    print("\nFull flow test passed.")
"""

# test JFE
def load_partners_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"partners.yaml not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid partners.yaml structure: {config_path}")

    return data


def get_partner_config(partners_config: dict[str, Any], partner: str) -> dict[str, Any]:
    partner = partner.upper()

    partners = partners_config.get("partners")
    if not isinstance(partners, dict):
        raise ValueError("partners.yaml must contain a top-level 'partners' dictionary")

    cfg = partners.get(partner)
    if not isinstance(cfg, dict):
        raise KeyError(f"Partner config not found for partner: {partner}")

    return cfg


def main() -> None:
    project_root = Path(__file__).resolve().parent

    partners_config_path = project_root / "config" / "partners.yaml"
    partners_config = load_partners_config(partners_config_path)

    partner_cfg = get_partner_config(partners_config, "JFE")
    urls = partner_cfg.get("urls") or {}

    base_url = urls.get("homepage")
    datasheet_url = urls.get("connection_datasheet")
    blanking_url = urls.get("blanking_dimensions")

    if not base_url:
        raise ValueError("JFE config missing urls.homepage")
    if not datasheet_url:
        raise ValueError("JFE config missing urls.connection_datasheet")
    if not blanking_url:
        raise ValueError("JFE config missing urls.blanking_dimensions")

    # 模拟最终 JFE mapper 输出
    mapped_data = {
        "partner": "JFE",
        "side": "upper",
        "drift_extraction": True,
        "connection": {
            "name": "JFEBEAR",
            "od": "3.500",
            "weight": "9.2",
            "grade": "L80-13CR",
            "friction": "API Modified",
            "coupling": "STD",
            "type": "BOX",
        },
    }

    adapter = JfeAdapter(
        base_url=base_url,
        datasheet_url=datasheet_url,
        blanking_url=blanking_url,
        logs_dir=project_root / "logs",
        headless=False,
        slow_mo=300,
        timeout_ms=10000,
        navigation_timeout_ms=60000,
    )

    try:
        adapter_result = adapter.run(mapped_data)
    finally:
        adapter.close()

    print("\n=== JFE Adapter Result ===")
    print(adapter_result)

    required_keys = {
        "tensile",
        "compression",
        "burst",
        "collapse",
        "od",
        "id",
        "external_length",
        "internal_length",
        "drift",
    }

    missing = required_keys - set(adapter_result.keys())
    if missing:
        raise AssertionError(f"JFE adapter result missing keys: {sorted(missing)}")

    if adapter_result["drift"] in {None, "", "NA"}:
        raise AssertionError("Expected drift value, but got empty or NA")

    print("\nJFE adapter test passed.")


if __name__ == "__main__":
    main()