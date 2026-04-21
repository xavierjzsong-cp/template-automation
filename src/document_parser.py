from __future__ import annotations

from pathlib import Path
from typing import Any

from src.parsers.pots_doc_parser import POTSDocParser


class DocumentParser:
    def __init__(self) -> None:
        self.pots_parser = POTSDocParser()

    def parse_docs(self, input_path: str | Path) -> dict[str, Any]:
        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(f"Documents not found: {input_path}")

        return self.pots_parser.parse(input_path)