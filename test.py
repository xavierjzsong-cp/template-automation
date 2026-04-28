from __future__ import annotations

from pathlib import Path

from src.config_loader import load_partners_config, get_partner_config
from src.document_parser import DocumentParser
from src.routers.partner_router import PartnerRouter
from src.mappers.vam_mapper import VamMapper
from src.site_adapters.vam_adapter import VamAdapter
from src.mappers.tsh_mapper import TshMapper
from src.site_adapters.tsh_adapter import TshAdapter
from src.writers.template_writer import TemplateWriter


# 测试整个流程
"""
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

    # 当前先只准备 VAM mapper
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

    top_adapter = None
    bottom_adapter = None

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

        if partner == "VAM":
            partner_cfg = get_partner_config(partners_config, "VAM")
            urls = partner_cfg.get("urls") or {}

            base_url = urls.get("homepage")
            configurator_url = urls.get("connection_datasheet")

            if not base_url:
                raise ValueError("VAM config missing urls.homepage")
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

            try:
                adapter_result = adapter.run(mapped_result)
            finally:
                adapter.close()

            print(f"\n=== Adapter Result ({partner} / {side}) ===")
            print(adapter_result)

            if side == "upper":
                top_adapter = adapter_result
            elif side == "lower":
                bottom_adapter = adapter_result

    write_result = writer.write(
        parsed=parsed,
        top_adapter=top_adapter,
        bottom_adapter=bottom_adapter,
        template_path=template_path,
        output_dir=output_dir,
    )
"""

# test TSH
def main() -> None:
    project_root = Path(__file__).resolve().parent

    partners_config_path = project_root / "config" / "partners.yaml"
    partners_config = load_partners_config(partners_config_path)

    tsh_cfg = get_partner_config(partners_config, "TSH")
    urls = tsh_cfg.get("urls") or {}

    base_url = urls.get("homepage")
    datasheet_url = urls.get("connection_datasheet")
    blanking_url = urls.get("blanking_dimensions")

    if not base_url:
        raise ValueError("TSH config missing urls.homepage")
    if not datasheet_url:
        raise ValueError("TSH config missing urls.connection_datasheet")
    if not blanking_url:
        raise ValueError("TSH config missing urls.blanking_dimensions")

    mapped_data = {
        "partner": "TSH",
        "side": "upper",
        "connection": {
            "name": "WEDGE 511",
            "od": "3.500",
            "weight": "9.20",
            "grade": "L80 Type 13Cr",
            "type": "BOX",
        },
    }

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

    try:
        result = adapter.run(mapped_data)

        print("\n=== TSH Adapter Result ===")
        print(result)

        required_keys = [
            "tensile",
            "compression",
            "burst",
            "collapse",
            "od",
            "id",
        ]

        for key in required_keys:
            if key not in result:
                raise AssertionError(f"Missing key in TSH result: {key}")

        if not result["od"].get("min") or not result["od"].get("max"):
            raise AssertionError(f"Invalid od result: {result['od']}")

        if not result["id"].get("min") or not result["id"].get("max"):
            raise AssertionError(f"Invalid id result: {result['id']}")

        print("\nTSH adapter test passed.")

    finally:
        adapter.close()

if __name__ == "__main__":
    main()