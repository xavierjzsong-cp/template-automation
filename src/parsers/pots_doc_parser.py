from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

from src.mappers.mapper_tables.product_type_map import PRODUCT_TYPE_ALIASES


class POTSDocParser:
    PARTNER_ALIASES = {
        "VAM": ["VAM"],
        "TSH": ["TSH"],
        "JFE": ["JFE"],
        "HT": ["SLHT-S", "SLHT"],
    }

    def parse(self, input_path: Path) -> dict[str, Any]:
        full_text = self._extract_text_from_docs(input_path, max_pages=2)
        cleaned_text = self._normalize_text(full_text)

        product_description = self._extract_product_description(cleaned_text)
        parsed_desc = (
            self._parse_product_description(product_description)
            if product_description
            else {}
        )

        result = {
            "source_file": str(input_path),
            "rev": self._extract_rev(cleaned_text),
            "part_number": self._extract_field_value(
                cleaned_text,
                field_name="CP Part Number",
            ),
            "product_type": parsed_desc.get("product_type") or self._extract_product_type_from_document(cleaned_text),
            "product_material_grade": parsed_desc.get("product_material_grade") or self._normalize_material_grade(
                self._extract_field_value(
                    cleaned_text,
                    field_name="Product Material Grade",
                )
            ),
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
            "overall_length": parsed_desc.get("overall_length") or self._extract_field_value(
                cleaned_text,
                field_name="Overall Length",
            ),
            "parse_warnings": parsed_desc.get("parse_warnings", []),
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

        warnings: list[str] = []

        normalized = self._normalize_description_text(description)

        product_type = self._extract_product_type_from_description(normalized)
        product_material_grade = self._extract_material_grade(normalized)
        overall_length = self._extract_overall_length(normalized)

        connection_text = self._remove_global_fields(
            text=normalized,
            product_type=product_type,
        )

        connection_segments = self._split_connection_segments(connection_text)

        if len(connection_segments) < 2:
            warnings.append(
                f"Expected 2 connection segments, but found {len(connection_segments)}. "
                f"connection_text={connection_text}"
            )

        parsed_connections = [
            self._build_connection_object(segment, warnings)
            for segment in connection_segments[:2]
        ]

        connections: dict[str, Any] = {
            "upper": None,
            "lower": None,
        }

        if len(parsed_connections) >= 1:
            connections["upper"] = parsed_connections[0]

        if len(parsed_connections) >= 2:
            connections["lower"] = parsed_connections[1]

        return {
            "product_type": product_type,
            "product_material_grade": product_material_grade,
            "overall_length": overall_length,
            "connections": connections,
            "parse_warnings": warnings,
        }

    def _normalize_description_text(self, text: str) -> str:
        text = self._clean_value(text) or ""

        replacements = {
            "“": '"',
            "”": '"',
            "″": '"',
            "＂": '"',
            "’": "'",
            "‘": "'",
            "–": "-",
            "—": "-",
            "×": " X ",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        text = text.upper()

        text = re.sub(r"\s+[X]\s+", " X ", text)

        text = re.sub(r"\b(BOX|PIN)\s*X(?=\s*\d)", r"\1 X ", text)

        text = re.sub(r"\b(BOX|PIN)\s+X(?=\d)", r"\1 X ", text)

        text = re.sub(r"(\d)(IN\b)", r"\1 \2", text)

        text = re.sub(r'(\d+(?:\.\d+)?)"\s*(LONG)\b', r'\1" \2', text)

        text = re.sub(r'(\d+(?:\.\d+)?)"\s*LONG\b', r'\1" LONG', text)

        text = text.replace(",", " , ")
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _extract_product_type_from_description(self, text: str) -> str | None:
        normalized_text = self._normalize_parse_text(text)

        for product_type, aliases in self._iter_product_type_aliases_by_length():
            for alias in aliases:
                if self._phrase_at_start(normalized_text, alias):
                    return product_type

        for product_type, aliases in self._iter_product_type_aliases_by_length():
            for alias in aliases:
                if self._phrase_exists(normalized_text, alias):
                    return product_type

        return None

    def _extract_product_type_from_document(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        checked_prefix_patterns = [
            r"^[☒☑✓✔]\s*(.+)$",
            r"^\[\s*[xX]\s*\]\s*(.+)$",
        ]

        for line in lines:
            for pattern in checked_prefix_patterns:
                match = re.match(pattern, line)
                if match:
                    candidate = self._normalize_description_text(match.group(1))
                    matched = self._match_product_type_option(candidate)
                    if matched:
                        return matched

        product_type_block = self._extract_product_type_block(text)
        if product_type_block:
            block = self._normalize_description_text(product_type_block)
            matched = self._match_product_type_option(block)
            if matched:
                return matched

        return None

    def _extract_product_type_block(self, text: str) -> str | None:
        start_match = re.search(r"Product Type", text, flags=re.IGNORECASE)
        end_match = re.search(r"Product Description", text, flags=re.IGNORECASE)

        if not start_match or not end_match:
            return None

        if end_match.start() <= start_match.end():
            return None

        return text[start_match.end():end_match.start()].strip()

    def _match_product_type_option(self, candidate: str) -> str | None:
        candidate_norm = self._normalize_parse_text(candidate)

        for product_type, aliases in self._iter_product_type_aliases_by_length():
            for alias in aliases:
                if self._normalize_parse_text(alias) == candidate_norm:
                    return product_type

        for product_type, aliases in self._iter_product_type_aliases_by_length():
            for alias in aliases:
                alias_norm = self._normalize_parse_text(alias)
                if self._phrase_exists(candidate_norm, alias_norm):
                    return product_type

        return None

    def _iter_product_type_aliases_by_length(self) -> list[tuple[str, list[str]]]:
        items = []

        for product_type, aliases in PRODUCT_TYPE_ALIASES.items():
            normalized_aliases = sorted(
                {self._normalize_parse_text(alias) for alias in aliases},
                key=len,
                reverse=True,
            )
            items.append((product_type, normalized_aliases))

        items.sort(
            key=lambda item: max(len(alias) for alias in item[1]),
            reverse=True,
        )

        return items

    def _phrase_at_start(self, text: str, phrase: str) -> bool:
        pattern = self._phrase_pattern(phrase)
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return bool(match and match.start() == 0)

    def _phrase_exists(self, text: str, phrase: str) -> bool:
        pattern = self._phrase_pattern(phrase)
        return bool(re.search(pattern, text, flags=re.IGNORECASE))

    def _phrase_pattern(self, phrase: str) -> str:
        escaped = re.escape(self._normalize_parse_text(phrase))
        escaped = escaped.replace(r"\ ", r"\s+")
        return rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])"

    def _normalize_parse_text(self, text: str) -> str:
        text = text.upper().strip()
        text = text.replace("\u00a0", " ")
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("–", "-").replace("—", "-")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_overall_length(self, text: str) -> str | None:
        patterns = [
            r"\bOAL\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:\"|IN|INCH)?\b",
            r"\bOVERALL\s+LENGTH\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:\"|IN|INCH)?\b",
            r"\bBASED\s+ON\s+(\d+(?:\.\d+)?)\s*(?:\"|IN|INCH)?\s+LONG\b",
            r"\b(\d+(?:\.\d+)?)\s*(?:\"|IN|INCH)\s+LONG\b",
            r"\b(\d+(?:\.\d+)?)\s+LONG\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return self._clean_number(match.group(1))

        return None

    def _extract_material_grade(self, text: str) -> str | None:
        patterns = [
            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[\(\[]\s*(\d+(?:\.\d+)?)\s*[\)\]]",

            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[- ]+\s*(\d+(?:\.\d+)?)\s*KSI\b",

            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[- ]?\s*(\d{2,3}(?:\.\d+)?)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                family = re.sub(r"\s+", "", match.group(1).upper())
                strength = self._clean_number(match.group(2))
                return f"{family}({strength})"

        return None

    def _normalize_material_grade(self, value: str | None) -> str | None:
        if not value:
            return None

        text = self._normalize_description_text(value)
        return self._extract_material_grade(text) or self._clean_value(value)

    def _remove_global_fields(
        self,
        text: str,
        product_type: str | None,
    ) -> str:
        cleaned = text

        if product_type:
            for alias in PRODUCT_TYPE_ALIASES.get(product_type, [product_type]):
                cleaned = re.sub(
                    self._phrase_pattern(alias),
                    " ",
                    cleaned,
                    count=1,
                    flags=re.IGNORECASE,
                )

        overall_length_patterns = [
            r"\bOAL\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:\"|IN|INCH)?\b",
            r"\bOVERALL\s+LENGTH\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:\"|IN|INCH)?\b",
            r"\bBASED\s+ON\s+\d+(?:\.\d+)?\s*(?:\"|IN|INCH)?\s+LONG\b",
            r"\b\d+(?:\.\d+)?\s*(?:\"|IN|INCH)\s+LONG\b",
            r"\b\d+(?:\.\d+)?\s+LONG\b",
        ]

        for pattern in overall_length_patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

        material_patterns = [
            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[\(\[]\s*\d+(?:\.\d+)?\s*[\)\]]",
            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[- ]+\s*\d+(?:\.\d+)?\s*KSI\b",
            r"\b((?:SUPER\s*)?S?13CR|13CR)\s*[- ]?\s*\d{2,3}(?:\.\d+)?\b",
        ]

        for pattern in material_patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.replace(",", " ")
        cleaned = re.sub(r"\s+-\s+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    def _split_connection_segments(self, text: str) -> list[str]:
        if not text:
            return []

        parts = re.split(r"\s+\bX\b\s+", text, maxsplit=1)

        return [
            part.strip(" ,;-")
            for part in parts
            if part and part.strip(" ,;-")
        ]

    def _build_connection_object(
        self,
        conn: str | None,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        if not conn:
            return None

        od, weight, od_weight_span = self._extract_od_and_weight(conn)

        connection_type = self._extract_connection_end_type(conn)
        family = self._extract_connection_family(conn)
        connection_name = self._extract_connection_name(
            conn=conn,
            od_weight_span=od_weight_span,
            connection_type=connection_type,
            family=family,
        )

        if od is None:
            warnings.append(f"Could not extract OD from connection segment: {conn}")

        if weight is None:
            warnings.append(f"Could not extract weight from connection segment: {conn}")

        if connection_type is None:
            warnings.append(f"Could not extract BOX/PIN from connection segment: {conn}")

        if family is None:
            warnings.append(f"Could not extract partner family from connection segment: {conn}")

        if connection_name is None:
            warnings.append(f"Could not extract connection name from connection segment: {conn}")

        return {
            "name": connection_name,
            "od": od,
            "weight": weight,
            "family": family,
            "type": connection_type,
        }

    def _extract_od_and_weight(
        self,
        conn: str,
    ) -> tuple[str | None, str | None, tuple[int, int] | None]:
        pattern = re.compile(
            r"""
            (?P<od>
                \d+(?:\.\d+)?
                (?:\s+\d+/\d+)?
            )
            \s*
            (?:"|IN|INCH)?
            \s+
            (?P<weight>\d+(?:\.\d+)?)
            \s*
            \#?
            """,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        match = pattern.search(conn)
        if not match:
            return None, None, None

        od_raw = match.group("od")
        weight_raw = match.group("weight")

        od = self._parse_od_value(od_raw)
        weight = self._clean_number(weight_raw)

        return od, weight, match.span()

    def _parse_od_value(self, value: str) -> str:
        value = value.strip()
        value = value.replace('"', "")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _extract_connection_end_type(self, conn: str | None) -> str | None:
        if not conn:
            return None

        matches = re.findall(r"\b(BOX|PIN)\b", conn, flags=re.IGNORECASE)
        if not matches:
            return None

        return matches[-1].upper()

    def _extract_connection_family(self, conn: str | None) -> str | None:
        if not conn:
            return None

        text = conn.upper()

        for family, aliases in self.PARTNER_ALIASES.items():
            for alias in aliases:
                if re.search(rf"\b{re.escape(alias.upper())}\b", text):
                    return family

        return None

    def _extract_connection_name(
        self,
        conn: str,
        od_weight_span: tuple[int, int] | None,
        connection_type: str | None,
        family: str | None,
    ) -> str | None:
        name = conn

        if od_weight_span is not None:
            start, end = od_weight_span
            name = conn[:start] + " " + conn[end:]

        name = name.replace('"', " ")
        name = name.replace("#", " ")

        if connection_type:
            name = re.sub(
                rf"\b{re.escape(connection_type)}\b",
                " ",
                name,
                flags=re.IGNORECASE,
            )

        name = re.sub(r"\bX\b", " ", name, flags=re.IGNORECASE)

        if family:
            name = self._remove_family_aliases_from_name(
                name=name,
                family=family,
            )

        name = name.replace(",", " ")
        name = re.sub(r"\s+-\s+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()

        return name if name else None

    def _remove_family_aliases_from_name(
        self,
        name: str,
        family: str,
    ) -> str:
        aliases = self.PARTNER_ALIASES.get(family, [])

        for alias in aliases:
            alias_upper = alias.upper()

            if family == "HT" and alias_upper in {"SLHT", "SLHT-S"}:
                continue

            name = re.sub(
                rf"\b{re.escape(alias_upper)}\b",
                " ",
                name,
                flags=re.IGNORECASE,
            )

        return name

    def _clean_number(self, value: str) -> str:
        value = value.strip()

        try:
            number = float(value)
        except ValueError:
            return value

        if number.is_integer():
            return str(int(number))

        return f"{number:.6f}".rstrip("0").rstrip(".")

    def _clean_value(self, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()
        value = re.sub(r"\s+", " ", value)

        return value if value else None