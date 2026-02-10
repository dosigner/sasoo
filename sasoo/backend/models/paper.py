"""
Data models for parsed papers and their components.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


@dataclass
class FigureReference:
    """A reference to a figure in the paper text (e.g., 'As shown in Fig. 1A...')."""
    text: str  # The sentence or context containing the reference
    page_number: int  # Page where this reference appears
    figure_label: str  # e.g., "1", "1A", "1B"


@dataclass
class SubCaption:
    """Represents a sub-figure caption (e.g., (A), (B), (C))."""
    label: str  # e.g., "A", "B", "C"
    text: str   # Description for this sub-figure
    references: list[FigureReference] = field(default_factory=list)  # In-text mentions


@dataclass
class StructuredCaption:
    """Structured caption with title and sub-captions."""
    title: str  # Main figure title (e.g., "Optical setup and measurements")
    sub_captions: list[SubCaption] = field(default_factory=list)
    references: list[FigureReference] = field(default_factory=list)  # All in-text mentions

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "title": self.title,
            "sub_captions": [
                {
                    "label": sc.label,
                    "text": sc.text,
                    "references": [
                        {"text": r.text, "page": r.page_number}
                        for r in sc.references
                    ]
                }
                for sc in self.sub_captions
            ],
            "references": [
                {"text": r.text, "page": r.page_number, "label": r.figure_label}
                for r in self.references
            ]
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "StructuredCaption":
        """Create from dictionary."""
        return cls(
            title=data.get("title", ""),
            sub_captions=[
                SubCaption(label=sc["label"], text=sc["text"])
                for sc in data.get("sub_captions", [])
            ]
        )

    def get_full_text(self) -> str:
        """Get full caption as plain text."""
        parts = [self.title]
        for sc in self.sub_captions:
            parts.append(f"({sc.label}) {sc.text}")
        return " ".join(parts)


@dataclass
class Figure:
    """Represents an extracted figure from a paper."""
    figure_id: str  # e.g., "figure_1" or "figure_1a" for sub-figures
    page_number: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    image_path: Path
    caption: str = ""  # Raw caption text (backward compatible)
    caption_bbox: Optional[tuple[float, float, float, float]] = None
    structured_caption: Optional[StructuredCaption] = None  # Parsed structured caption
    parent_figure_id: Optional[str] = None  # For sub-figures, points to main figure
    sub_label: Optional[str] = None  # e.g., "A", "B", "C" for sub-figures


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
