"""
PDF Parser for extracting text, figures, tables, and metadata from research papers.

This service uses PyMuPDF (fitz) for text and image extraction, and pdfplumber
for table extraction. It implements intelligent caption matching and creates
structured output directories.
"""
import re
import fitz  # PyMuPDF
import pdfplumber
from pathlib import Path
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import io

from models.paper import ParsedPaper, Figure, Table, Metadata


class PdfParserError(Exception):
    """Base exception for PDF parsing errors."""
    pass


class FileSizeExceededError(PdfParserError):
    """Raised when PDF file exceeds maximum size limit."""
    pass


class PdfParser:
    """
    Async PDF parser that extracts comprehensive information from research papers.

    Features:
    - Text extraction with layout preservation
    - Figure extraction with caption matching
    - Table extraction with structure preservation
    - Metadata extraction from PDF properties and first page
    - Organized output directory structure
    """

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    FIGURES_SUBDIR = "figures"
    TABLES_SUBDIR = "tables"

    # Caption detection patterns
    CAPTION_PATTERNS = [
        r"(Figure|Fig\.?)\s+(\d+[a-zA-Z]?)[:\.\s]+(.+?)(?=\n\n|\n[A-Z]|$)",
        r"(Table|Tbl\.?)\s+(\d+[a-zA-Z]?)[:\.\s]+(.+?)(?=\n\n|\n[A-Z]|$)",
    ]

    # Metadata extraction patterns
    TITLE_PATTERNS = [
        r"^(.{10,200})\n",  # First substantial line
    ]

    AUTHOR_PATTERNS = [
        r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)",  # FirstName LastName or F. LastName
    ]

    DOI_PATTERN = r"(?:doi:|DOI:)?\s*(10\.\d{4,}/[^\s]+)"
    YEAR_PATTERN = r"\b(19|20)\d{2}\b"

    def __init__(self, output_base_dir: Path = Path("./papers")):
        """
        Initialize PDF parser.

        Args:
            output_base_dir: Base directory for storing extracted paper data
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def parse(self, pdf_path: str | Path) -> ParsedPaper:
        """
        Parse a PDF file and extract all components.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            ParsedPaper object with all extracted data

        Raises:
            FileSizeExceededError: If PDF exceeds MAX_FILE_SIZE
            PdfParserError: If parsing fails
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise PdfParserError(f"PDF file not found: {pdf_path}")

        # Check file size
        file_size = pdf_path.stat().st_size
        if file_size > self.MAX_FILE_SIZE:
            raise FileSizeExceededError(
                f"PDF size ({file_size / 1024 / 1024:.1f}MB) exceeds "
                f"maximum allowed ({self.MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
            )

        # Run blocking I/O operations in executor
        loop = asyncio.get_event_loop()

        # Extract metadata first to create proper directory structure
        metadata = await loop.run_in_executor(
            self._executor,
            self._extract_metadata,
            pdf_path
        )

        # Create output directory
        base_path = self._create_output_directory(metadata, pdf_path)
        figures_dir = base_path / self.FIGURES_SUBDIR
        figures_dir.mkdir(exist_ok=True)

        # Extract components in parallel
        text_task = loop.run_in_executor(
            self._executor,
            self._extract_text,
            pdf_path
        )

        figures_task = loop.run_in_executor(
            self._executor,
            self._extract_figures,
            pdf_path,
            figures_dir
        )

        tables_task = loop.run_in_executor(
            self._executor,
            self._extract_tables,
            pdf_path
        )

        # Wait for all extractions
        full_text, figures, tables = await asyncio.gather(
            text_task, figures_task, tables_task
        )

        # Match captions with figures and tables
        figures = self._match_captions_to_figures(full_text, figures)
        tables = self._match_captions_to_tables(full_text, tables)

        return ParsedPaper(
            full_text=full_text,
            figures=figures,
            tables=tables,
            metadata=metadata,
            base_path=base_path,
            figures_dir=figures_dir
        )

    def _extract_metadata(self, pdf_path: Path) -> Metadata:
        """Extract metadata from PDF properties and first page."""
        metadata = Metadata(
            file_name=pdf_path.name,
            file_size_bytes=pdf_path.stat().st_size
        )

        doc = fitz.open(pdf_path)
        metadata.page_count = len(doc)

        # PDF metadata
        pdf_meta = doc.metadata
        if pdf_meta:
            metadata.pdf_creator = pdf_meta.get("creator", "")
            metadata.pdf_producer = pdf_meta.get("producer", "")
            metadata.pdf_creation_date = pdf_meta.get("creationDate", "")

            # Try to get title from metadata
            if pdf_meta.get("title"):
                metadata.title = pdf_meta["title"]

            if pdf_meta.get("author"):
                metadata.authors = [pdf_meta["author"]]

        # Extract from first page text
        if len(doc) > 0:
            first_page_text = doc[0].get_text()

            # Extract title if not found in metadata
            if not metadata.title:
                metadata.title = self._extract_title(first_page_text)

            # Extract authors
            if not metadata.authors:
                metadata.authors = self._extract_authors(first_page_text)

            # Extract DOI
            doi_match = re.search(self.DOI_PATTERN, first_page_text, re.IGNORECASE)
            if doi_match:
                metadata.doi = doi_match.group(1)

            # Extract year
            year_matches = re.findall(self.YEAR_PATTERN, first_page_text)
            if year_matches:
                # Take the most recent year found
                metadata.year = max(int(y) for y in year_matches)

        doc.close()
        return metadata

    def _extract_title(self, first_page_text: str) -> str:
        """Extract paper title from first page text."""
        lines = [l.strip() for l in first_page_text.split('\n') if l.strip()]

        # Title is usually the first substantial line (not metadata)
        for line in lines[:10]:  # Check first 10 lines
            # Skip short lines, page numbers, headers
            if (len(line) > 20 and
                not re.match(r'^\d+$', line) and
                not re.match(r'^Page \d+', line, re.IGNORECASE) and
                not re.match(r'^[A-Z\s]+$', line)):  # Skip all-caps headers
                return line

        return lines[0] if lines else "Unknown Title"

    def _extract_authors(self, first_page_text: str) -> list[str]:
        """Extract author names from first page text."""
        lines = first_page_text.split('\n')[:20]  # Check first 20 lines
        authors = []

        for line in lines:
            # Look for lines with name-like patterns
            matches = re.findall(self.AUTHOR_PATTERNS[0], line)
            if matches:
                authors.extend(matches)

            # Stop at abstract or introduction
            if re.search(r'\babstract\b|\bintroduction\b', line, re.IGNORECASE):
                break

        # Deduplicate and limit
        seen = set()
        unique_authors = []
        for author in authors:
            author_clean = author.strip()
            if author_clean and author_clean not in seen:
                seen.add(author_clean)
                unique_authors.append(author_clean)

        return unique_authors[:10]  # Limit to 10 authors

    def _create_output_directory(self, metadata: Metadata, pdf_path: Path) -> Path:
        """
        Create organized output directory: {Year}_{FirstAuthor}_{ShortTitle}/

        Args:
            metadata: Extracted metadata
            pdf_path: Original PDF path

        Returns:
            Path to created directory
        """
        # Build directory name
        year = str(metadata.year) if metadata.year else "Unknown"

        first_author = "Unknown"
        if metadata.authors:
            # Get last name of first author
            first_author = metadata.authors[0].split()[-1]

        # Shorten title to ~30 chars, remove special chars
        title = metadata.title[:30] if metadata.title else pdf_path.stem
        title_clean = re.sub(r'[^\w\s-]', '', title).strip()
        title_clean = re.sub(r'[-\s]+', '_', title_clean)

        dir_name = f"{year}_{first_author}_{title_clean}"

        # Create directory
        output_dir = self.output_base_dir / dir_name
        output_dir.mkdir(parents=True, exist_ok=True)

        return output_dir

    def _extract_text(self, pdf_path: Path) -> str:
        """Extract full text from PDF with layout preservation."""
        doc = fitz.open(pdf_path)
        full_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            full_text.append(f"\n--- Page {page_num + 1} ---\n")
            full_text.append(text)

        doc.close()
        return "".join(full_text)

    def _extract_figures(self, pdf_path: Path, figures_dir: Path) -> list[Figure]:
        """
        Extract figures from PDF as images.

        Args:
            pdf_path: Path to PDF
            figures_dir: Directory to save figure images

        Returns:
            List of Figure objects
        """
        doc = fitz.open(pdf_path)
        figures = []
        figure_counter = 1

        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images()

            for img_index, img in enumerate(image_list):
                try:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]

                    # Get image position (bbox)
                    # This is approximate - PyMuPDF doesn't always give exact positions
                    img_rects = page.get_image_rects(xref)
                    bbox = img_rects[0] if img_rects else (0, 0, 100, 100)

                    # Filter out small images (likely icons/logos)
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    if width < 50 or height < 50:
                        continue

                    # Save image
                    figure_id = f"figure_{figure_counter}"
                    image_filename = f"{figure_id}.png"
                    image_path = figures_dir / image_filename

                    # Convert to PNG for consistency
                    img_obj = Image.open(io.BytesIO(image_bytes))
                    img_obj.save(image_path, "PNG")

                    figures.append(Figure(
                        figure_id=figure_id,
                        page_number=page_num + 1,
                        bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        image_path=image_path
                    ))

                    figure_counter += 1

                except Exception as e:
                    # Skip problematic images
                    continue

        doc.close()
        return figures

    def _extract_tables(self, pdf_path: Path) -> list[Table]:
        """
        Extract tables from PDF using pdfplumber.

        Args:
            pdf_path: Path to PDF

        Returns:
            List of Table objects
        """
        tables = []
        table_counter = 1

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_tables = page.find_tables()

                for table in page_tables:
                    try:
                        # Extract table data
                        table_data = table.extract()
                        if not table_data:
                            continue

                        # Get bounding box
                        bbox = table.bbox

                        table_id = f"table_{table_counter}"
                        tables.append(Table(
                            table_id=table_id,
                            page_number=page_num + 1,
                            bbox=bbox,
                            data=table_data
                        ))

                        table_counter += 1

                    except Exception as e:
                        # Skip problematic tables
                        continue

        return tables

    def _match_captions_to_figures(
        self,
        full_text: str,
        figures: list[Figure]
    ) -> list[Figure]:
        """
        Match figure captions to extracted figures using proximity heuristics.

        Args:
            full_text: Full text of the paper
            figures: List of extracted figures

        Returns:
            Updated list of figures with captions
        """
        # Find all figure captions in text
        caption_pattern = re.compile(
            r"(Figure|Fig\.?)\s+(\d+[a-zA-Z]?)[:\.\s]+(.+?)(?=\n\n|Figure|Fig\.|Table|\n[A-Z][a-z]+\s+\d+|$)",
            re.IGNORECASE | re.DOTALL
        )

        captions = {}
        for match in caption_pattern.finditer(full_text):
            fig_num = match.group(2)
            caption_text = match.group(3).strip()
            # Clean up caption (remove excessive whitespace)
            caption_text = re.sub(r'\s+', ' ', caption_text)
            captions[fig_num] = caption_text

        # Match captions to figures based on figure number
        for i, figure in enumerate(figures):
            # Try to match by sequential numbering
            fig_num = str(i + 1)
            if fig_num in captions:
                figure.caption = captions[fig_num]
            elif f"{i + 1}a" in captions:
                # Handle subfigures
                figure.caption = captions[f"{i + 1}a"]

        return figures

    def _match_captions_to_tables(
        self,
        full_text: str,
        tables: list[Table]
    ) -> list[Table]:
        """
        Match table captions to extracted tables using proximity heuristics.

        Args:
            full_text: Full text of the paper
            tables: List of extracted tables

        Returns:
            Updated list of tables with captions
        """
        # Find all table captions in text
        caption_pattern = re.compile(
            r"(Table|Tbl\.?)\s+(\d+[a-zA-Z]?)[:\.\s]+(.+?)(?=\n\n|Table|Tbl\.|Figure|\n[A-Z][a-z]+\s+\d+|$)",
            re.IGNORECASE | re.DOTALL
        )

        captions = {}
        for match in caption_pattern.finditer(full_text):
            tbl_num = match.group(2)
            caption_text = match.group(3).strip()
            # Clean up caption
            caption_text = re.sub(r'\s+', ' ', caption_text)
            captions[tbl_num] = caption_text

        # Match captions to tables
        for i, table in enumerate(tables):
            tbl_num = str(i + 1)
            if tbl_num in captions:
                table.caption = captions[tbl_num]

        return tables

    async def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)

    def __del__(self):
        """Ensure cleanup on deletion."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)
