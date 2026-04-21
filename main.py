from pathlib import Path
from src.config_loader import load_yaml
from src.site_adapters.vam_adapter import VamAdapter


def main() -> None:
    project_root = Path(__file__).resolve().parent
    partners_cfg = load_yaml(project_root / "config" / "partners.yaml")
    vam_cfg = partners_cfg["partners"]["VAM"]

    adapter = VamAdapter(
        base_url=vam_cfg["base_url"],
        configurator_url=vam_cfg["configurator_url"],
        output_dir=project_root / "output_docs",
        logs_dir=project_root / "logs",
        headless=vam_cfg.get("headless", False),
        slow_mo=vam_cfg.get("slow_mo", 500),
        timeout_ms=vam_cfg.get("timeout_ms", 10000),
    )

    try:
        adapter.run(vam_cfg["hardcoded_request"])
        print("V1 flow completed. Check output/ and logs/ folders.")
    finally:
        adapter.close()


if __name__ == "__main__":
    main()