from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.parsers.pots_doc_parser import POTSDocParser
from src.routers.partner_router import PartnerRouter

from src.mappers.vam_mapper import VamMapper
from src.mappers.tsh_mapper import TshMapper
from src.mappers.jfe_mapper import JfeMapper
from src.mappers.ht_mapper import HtMapper
from src.mappers.coating_mapper import CoatingMapper

from src.adapters.vam_adapter import VamAdapter
from src.adapters.tsh_adapter import TshAdapter
from src.adapters.jfe_adapter import JfeAdapter
from src.adapters.ht_adapter import HtAdapter

from src.writers.template_writer import TemplateWriter


StatusCallback = Callable[[str], None]


@dataclass
class GenerationRequest:
    input_path: Path
    template_path: Path
    output_dir: Path
    user_name: str | None = None
    show_browser: bool = False


@dataclass
class GenerationResult:
    parsed: dict[str, Any]
    routing_result: dict[str, Any]
    mapped_results: list[dict[str, Any]]
    coating_data: dict[str, Any]
    top_adapter: dict[str, Any] | None
    bottom_adapter: dict[str, Any] | None
    writer_result: dict[str, Any]

    @property
    def output_file(self) -> str:
        return self.writer_result.get("output_file", "")


class TemplateGenerationService:

    SUPPORTED_TEMPLATE_SUFFIXES = {
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".xltm",
    }

    def __init__(
        self,
        project_root: Path | None = None,
        partners_config_path: Path | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.partners_config_path = (
            partners_config_path
            or self.project_root / "config" / "partners.yaml"
        )

    def generate(
        self,
        request: GenerationRequest,
        status_callback: StatusCallback | None = None,
    ) -> GenerationResult:
        self._status(status_callback, "Checking input information...")
        self._validate_request(request)

        self._status(status_callback, "Loading configuration...")
        partners_config = self._load_partners_config(self.partners_config_path)

        parser = POTSDocParser()
        router = PartnerRouter()
        writer = TemplateWriter()
        coating_mapper = CoatingMapper()

        mapper_registry = {
            "VAM": VamMapper(),
            "TSH": TshMapper(),
            "JFE": JfeMapper(),
            "HT": HtMapper(),
        }

        self._status(status_callback, "Reading input document...")
        parsed = parser.parse(request.input_path)

        self._status(status_callback, "Identifying connection details...")
        routing_result = router.route(parsed)

        targets = routing_result.get("targets") or []
        if not targets:
            raise RuntimeError("No partner targets were found from the parsed input.")

        mapped_results: list[dict[str, Any]] = []
        top_adapter: dict[str, Any] | None = None
        bottom_adapter: dict[str, Any] | None = None

        for target in targets:
            partner = (target.get("partner") or "").upper()
            side = target.get("side")

            mapper = mapper_registry.get(partner)
            if mapper is None:
                raise RuntimeError(
                    f"No mapper registered for partner: {partner}. "
                    f"Target={target}"
                )

            mapped_result = mapper.build_mapped_data(
                target=target,
                shared_data=routing_result.get("shared_data"),
            )
            mapped_results.append(mapped_result)

            if side == "upper":
                self._status(status_callback, "Retrieving top thread data...")
            elif side == "lower":
                self._status(status_callback, "Retrieving bottom thread data...")
            else:
                self._status(status_callback, "Retrieving thread data...")

            adapter_result = self._run_adapter_for_target(
                partner=partner,
                side=side,
                mapped_result=mapped_result,
                partners_config=partners_config,
                show_browser=request.show_browser,
            )

            if side == "upper":
                top_adapter = adapter_result
            elif side == "lower":
                bottom_adapter = adapter_result

        coating_data = coating_mapper.build_mapped_data(routing_result)

        self._status(status_callback, "Filling Excel template...")
        writer_result = writer.write(
            parsed=parsed,
            top_adapter=top_adapter,
            bottom_adapter=bottom_adapter,
            template_path=request.template_path,
            output_dir=request.output_dir,
            user_name=request.user_name,
            coating_data=coating_data,
        )

        self._status(status_callback, "Saving output file...")

        return GenerationResult(
            parsed=parsed,
            routing_result=routing_result,
            mapped_results=mapped_results,
            coating_data=coating_data,
            top_adapter=top_adapter,
            bottom_adapter=bottom_adapter,
            writer_result=writer_result,
        )

    def _run_adapter_for_target(
        self,
        partner: str,
        side: str,
        mapped_result: dict[str, Any],
        partners_config: dict[str, Any],
        show_browser: bool,
    ) -> dict[str, Any]:
        partner_cfg = self._get_partner_config(partners_config, partner)
        urls = partner_cfg.get("urls") or {}

        base_url = urls.get("homepage")
        if not base_url:
            raise ValueError(f"{partner} config missing urls.homepage")

        headless = not show_browser

        if partner == "VAM":
            configurator_url = urls.get("connection_datasheet")
            if not configurator_url:
                raise ValueError("VAM config missing urls.connection_datasheet")

            adapter = VamAdapter(
                base_url=base_url,
                configurator_url=configurator_url,
                logs_dir=self.project_root / "logs",
                headless=headless,
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
                logs_dir=self.project_root / "logs",
                headless=headless,
                slow_mo=300,
                timeout_ms=10000,
                navigation_timeout_ms=60000,
            )

        elif partner == "JFE":
            datasheet_url = urls.get("connection_datasheet")
            blanking_url = urls.get("blanking_dimensions")

            if not datasheet_url:
                raise ValueError("JFE config missing urls.connection_datasheet")
            if not blanking_url:
                raise ValueError("JFE config missing urls.blanking_dimensions")

            adapter = JfeAdapter(
                base_url=base_url,
                datasheet_url=datasheet_url,
                blanking_url=blanking_url,
                logs_dir=self.project_root / "logs",
                headless=headless,
                slow_mo=300,
                timeout_ms=10000,
                navigation_timeout_ms=60000,
            )

        elif partner == "HT":
            datasheet_url = urls.get("connection_datasheet")
            if not datasheet_url:
                raise ValueError("HT config missing urls.connection_datasheet")

            adapter = HtAdapter(
                base_url=base_url,
                datasheet_url=datasheet_url,
                logs_dir=self.project_root / "logs",
                headless=headless,
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

        self._validate_adapter_result(partner, side, adapter_result)

        return adapter_result

    def _validate_adapter_result(
        self,
        partner: str,
        side: str,
        adapter_result: dict[str, Any],
    ) -> None:
        required_fields = [
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

        missing = [
            field for field in required_fields
            if field not in adapter_result
        ]

        if missing:
            raise RuntimeError(
                f"{partner} adapter result for {side} thread missing fields: {missing}. "
                f"adapter_result={adapter_result}"
            )

    def _validate_request(self, request: GenerationRequest) -> None:
        if not request.input_path.exists():
            raise FileNotFoundError(f"Input PDF not found: {request.input_path}")

        if request.input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Input file must be PDF: {request.input_path}")

        if not request.template_path.exists():
            raise FileNotFoundError(f"Template file not found: {request.template_path}")

        if request.template_path.suffix.lower() not in self.SUPPORTED_TEMPLATE_SUFFIXES:
            raise ValueError(
                "Template file must be an Excel file supported by openpyxl: "
                ".xlsx, .xlsm, .xltx, or .xltm"
            )

        request.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_partners_config(self, config_path: Path) -> dict[str, Any]:
        if not config_path.exists():
            raise FileNotFoundError(f"partners.yaml not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid partners.yaml structure: {config_path}")

        return data

    def _get_partner_config(
        self,
        partners_config: dict[str, Any],
        partner: str,
    ) -> dict[str, Any]:
        partner = partner.upper()

        if "partners" in partners_config and isinstance(partners_config["partners"], dict):
            cfg = partners_config["partners"].get(partner)
            if cfg:
                return cfg

        cfg = partners_config.get(partner)
        if cfg:
            return cfg

        raise KeyError(f"Partner config not found for partner: {partner}")

    def _status(
        self,
        status_callback: StatusCallback | None,
        message: str,
    ) -> None:
        if status_callback:
            status_callback(message)