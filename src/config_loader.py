from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a dict: {path}")

    return data


def load_partners_config(path: str | Path = "config/partners.yml") -> dict[str, Any]:
    data = load_yaml(path)

    if "partners" not in data or not isinstance(data["partners"], dict):
        raise ValueError("Invalid partners.yml: missing top-level 'partners' mapping")

    return data


def get_partner_config(
    partners_config: dict[str, Any],
    partner_name: str,
) -> dict[str, Any]:
    partners = partners_config.get("partners") or {}

    if partner_name not in partners:
        raise KeyError(f"Partner config not found for: {partner_name}")

    cfg = partners[partner_name]
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config for partner: {partner_name}")

    return cfg