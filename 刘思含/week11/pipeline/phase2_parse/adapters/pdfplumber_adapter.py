"""pdfplumber-backed parser adapter."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber

from pipeline.common.types import (
    ImageBlock,
    PageText,
    ParsedDocument,
    TableBlock,
)

LOGGER = logging.getLogger("phase2.adapter")


def _clean_cell(value: Any) -> str:
    """Normalize a table cell."""
    if value is None:
        return ""
    return " ".join(str(value).split())


class PdfplumberAdapter:
    """Extract text, tables and images with pdfplumber."""

    name = "pdfplumber"

    def __init__(self) -> None:
        self.version = getattr(pdfplumber, "__version__", "unknown")

    def parse(self, pdf_path: Path) -> ParsedDocument:
        """Parse *pdf_path* into a ParsedDocument."""
        pdf_path = Path(pdf_path)
        page_texts: list[PageText] = []
        tables: list[TableBlock] = []
        images: list[ImageBlock] = []

        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_texts.append(
                    PageText(
                        page=page_number,
                        text=text,
                        lines=text.splitlines(),
                    )
                )

                try:
                    raw_tables = page.extract_tables()
                except Exception as exc:  # malformed page: record and continue
                    LOGGER.warning(
                        "table extraction failed on %s page %s: %s",
                        pdf_path,
                        page_number,
                        exc,
                    )
                    raw_tables = []
                for table in raw_tables:
                    if not table:
                        continue
                    rows = [[_clean_cell(cell) for cell in row] for row in table]
                    tables.append(TableBlock(page=page_number, rows=rows))

                for index, image in enumerate(page.images):
                    try:
                        block = self._extract_image(page, page_number, index, image)
                    except Exception as exc:  # image crop can fail on odd PDFs
                        LOGGER.warning(
                            "image extraction failed on %s page %s: %s",
                            pdf_path,
                            page_number,
                            exc,
                        )
                        continue
                    if block is not None:
                        images.append(block)

        return ParsedDocument(
            source_file=pdf_path.name,
            page_count=len(page_texts),
            text_blocks=page_texts,
            tables=tables,
            images=images,
            metadata={
                "adapter": self.name,
                "adapter_version": self.version,
                "pdf_path": pdf_path.as_posix(),
            },
        )

    @staticmethod
    def _extract_image(
        page: pdfplumber.page.Page,
        page_number: int,
        index: int,
        image: dict[str, Any],
    ) -> ImageBlock | None:
        """Crop one image and return it as PNG bytes."""
        width = float(image.get("width") or 0)
        height = float(image.get("height") or 0)
        if width <= 0 or height <= 0:
            return None
        bbox = (
            float(image["x0"]),
            float(image["top"]),
            float(image["x1"]),
            float(image["bottom"]),
        )
        rendered = page.crop(bbox).to_image(resolution=200)
        buffer = BytesIO()
        rendered.save(buffer, format="PNG")
        srcsize = image.get("srcsize")
        return ImageBlock(
            page=page_number,
            index_on_page=index,
            image_bytes=buffer.getvalue(),
            ext="png",
            bbox=bbox,
            srcsize=(
                int(srcsize[0]),
                int(srcsize[1]),
            )
            if srcsize
            else None,
        )
