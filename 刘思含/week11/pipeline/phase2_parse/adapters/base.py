"""Parser adapter protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pipeline.common.types import ParsedDocument


class ParserAdapter(Protocol):
    """Protocol implemented by PDF parser adapters."""

    name: str
    version: str

    def parse(self, pdf_path: Path) -> ParsedDocument:
        """Parse *pdf_path* into a :class:`ParsedDocument`."""
        ...
