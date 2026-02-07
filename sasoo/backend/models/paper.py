"""
Data models for parsed papers and their components.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Figure:
    """Represents an extracted figure from a paper."""
    figure_id: str  # e.g., "figure_1"
    page_number: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    image_path: Path
    caption: str = ""
    caption_bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class Table:
    """Represents an extracted table from a paper."""
    table_id: str  # e.g., "table_1"
    page_number: int
    bbox: tuple[float, float, float, float]
    data: list[list[str]]  # 2D array of cell contents
    caption: str = ""
    caption_bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class Metadata:
    """Paper metadata extracted from PDF."""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: Optional[int] = None
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""

    # File info
    file_name: str = ""
    file_size_bytes: int = 0
    page_count: int = 0

    # PDF metadata
    pdf_creator: str = ""
    pdf_producer: str = ""
    pdf_creation_date: str = ""


@dataclass
class ParsedPaper:
    """Complete parsed paper with text, figures, tables, and metadata."""
    full_text: str
    figures: list[Figure] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)

    # Storage paths
    base_path: Optional[Path] = None  # {Year}_{FirstAuthor}_{ShortTitle}/
    figures_dir: Optional[Path] = None

    def get_figure_by_id(self, figure_id: str) -> Optional[Figure]:
        """Get a specific figure by ID."""
        for fig in self.figures:
            if fig.figure_id == figure_id:
                return fig
        return None

    def get_table_by_id(self, table_id: str) -> Optional[Table]:
        """Get a specific table by ID."""
        for tbl in self.tables:
            if tbl.table_id == table_id:
                return tbl
        return None
