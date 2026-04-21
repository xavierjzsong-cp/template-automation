from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz


class POTSDocParser:
    def parse(self, input_path: Path) -> dict[str, Any]:
        full_text = self._extract_text_from_docs(input_path, max_pages=2)
        cleaned_text = self._normalize_text(full_text)

        product_description = self._extract_product_description(cleaned_text)
        parsed_desc = self._parse_product_description(product_description) if product_description else {}

        result = {
            "source_file": str(input_path),
            "rev": self._extract_rev(cleaned_text),
            "part_number": self._extract_field_value(
                cleaned_text,
                field_name="CP Part Number",
            ),
            "product_type": parsed_desc.get("product_type"),
            "product_material_grade": parsed_desc.get("product_material_grade"),
            "product_description": product_description,
            "connections": parsed_desc.get("connections"),
            "ansi_nace": self._extract_field_value(
                cleaned_text,
                field_name="ANSI/NACE MR0175/ISO 15156 (Yes/No)",
            ),
            "qcp": self._extract_field_value(
                cleaned_text,
                field_name="QCP (Standard/Client Specific)",
            ),
            "overall_length": parsed_desc.get("product_length") or self._extract_field_value(
                cleaned_text,
                field_name="Overall Length",
            ),
            "raw_text": cleaned_text,
        }

        return result

    def _extract_text_from_docs(self, input_path: Path, max_pages: int = 2) -> str:
        doc = fitz.open(input_path)
        texts: list[str] = []

        try:
            for page_index in range(min(max_pages, len(doc))):
                page = doc[page_index]
                page_text = page.get_text("text")
                texts.append(page_text)
        finally:
            doc.close()

        return "\n".join(texts)

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\u00a0", " ")
        text = text.replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    def _extract_rev(self, text: str) -> str | None:
        patterns = [
            r"POTS Document number:\s*\d+\s+Rev:\s*([A-Za-z0-9\-]+)",
            r"Rev:\s*([A-Za-z0-9\-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_product_description(self, text: str) -> str | None:
        pattern = (
            r"Product Description\s+(.+?)\s+"
            r"ANSI/NACE MR0175/ISO 15156 \(Yes/No\)"
        )

        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            value = self._clean_value(value)
            return value

        return None

    def _extract_field_value(self, text: str, field_name: str) -> str | None:
        escaped = re.escape(field_name)

        patterns = [
            rf"{escaped}\s+(.+?)(?:\n|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                value = self._clean_value(value)
                if value:
                    return value

        return None

    def _parse_product_description(self, description: str) -> dict[str, Any]:
        description = self._clean_value(description)
        if not description:
            return {}

        description = self._normalize_description_text(description)

        result: dict[str, Any] = {
            "product_type": None,
            "product_material_grade": None,
            "product_length": None,
            "connections": {
                "upper": None,
                "lower": None,
            },
        }

        parts = [p.strip() for p in description.split(",") if p.strip()]

        if len(parts) >= 1:
            result["product_type"] = self._clean_value(parts[0])

        if len(parts) >= 2:
            result["product_material_grade"] = self._clean_value(parts[1])

        if len(parts) >= 3:
            result["product_length"] = self._extract_length_number(parts[2])

        if len(parts) >= 4:
            conn_part = ",".join(parts[3:]).strip()
            upper_conn_raw, lower_conn_raw = self._split_connections(conn_part)

            result["connections"]["upper"] = self._build_connection_object(upper_conn_raw)
            result["connections"]["lower"] = self._build_connection_object(lower_conn_raw)

        return result

    def _normalize_description_text(self, text: str) -> str:
        text = self._clean_value(text) or ""

        text = re.sub(r"\b(BOX|PIN)X(\d)", r"\1 X \2", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(BOX|PIN)\s*[xX]\s*(\d)", r"\1 X \2", text, flags=re.IGNORECASE)

        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _split_connections(self, conn_text: str) -> tuple[str | None, str | None]:
        conn_text = self._normalize_description_text(conn_text)

        parts = re.split(r"\s+X\s+", conn_text, maxsplit=1, flags=re.IGNORECASE)

        if len(parts) == 2:
            return self._clean_value(parts[0]), self._clean_value(parts[1])

        return self._clean_value(conn_text), None

    def _build_connection_object(self, conn: str | None) -> dict[str, Any] | None:
        if not conn:
            return None

        od = self._extract_connection_od(conn)
        weight = self._extract_connection_weight(conn)
        connection_name = self._extract_connection_name(conn)
        family = self._extract_connection_family(connection_name)
        connection_type = self._extract_connection_end_type(connection_name)

        return {
            "name": connection_name,
            "od": od,
            "weight": weight,
            "family": family,
            "type": connection_type,
        }

    def _extract_connection_od(self, conn: str) -> str | None:
        match = re.match(r"^\s*([\d.]+)", conn)
        return match.group(1) if match else None

    def _extract_connection_weight(self, conn: str) -> str | None:
        match = re.match(r"^\s*[\d.]+\s+([\d.]+)", conn)
        return match.group(1) if match else None

    def _extract_connection_name(self, conn: str) -> str | None:
        match = re.match(r"^\s*[\d.]+\s+[\d.]+\s+(.+)$", conn)
        if match:
            return self._clean_value(match.group(1))
        return None

    def _extract_connection_family(self, connection_name: str | None) -> str | None:
        if not connection_name:
            return None

        text = connection_name.strip()
        if not text:
            return None

        parts = text.split()
        return parts[0].upper() if parts else None

    def _extract_connection_end_type(self, connection_name: str | None) -> str | None:
        if not connection_name:
            return None

        text = connection_name.strip().upper()

        if text.endswith(" BOX"):
            return "BOX"
        if text.endswith(" PIN"):
            return "PIN"

        return None

    def _extract_length_number(self, text: str) -> str | None:
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        return match.group(1) if match else None

    def _clean_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        value = re.sub(r"\s+", " ", value)
        return value if value else None