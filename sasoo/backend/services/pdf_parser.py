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

from models.paper import ParsedPaper, Figure, Table, Metadata, StructuredCaption, SubCaption, FigureReference


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

        # Parse structured captions and extract in-text references
        figures = self.add_structured_captions(figures)
        figures = self.extract_figure_references(full_text, figures)

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
        Extract figures from PDF by rendering pages and cropping figure regions.

        This approach renders entire pages as images and identifies figure regions
        based on caption positions, avoiding the fragmentation issue with embedded
        image extraction.

        Args:
            pdf_path: Path to PDF
            figures_dir: Directory to save figure images

        Returns:
            List of Figure objects
        """
        doc = fitz.open(pdf_path)
        figures = []

        # First pass: find all figure captions with their positions
        figure_regions = self._find_figure_regions(doc)

        # Fallback: if no captions found, use large embedded images
        if not figure_regions:
            figures = self._extract_large_images_fallback(doc, figures_dir)
            doc.close()
            return figures

        # Second pass: render and crop each figure region
        for region in figure_regions:
            try:
                page = doc[region["page_num"]]

                # Render page at high resolution (2x for clarity)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)

                # Convert to PIL Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # Scale bbox coordinates
                bbox = region["bbox"]
                scaled_bbox = (
                    int(bbox[0] * zoom),
                    int(bbox[1] * zoom),
                    int(bbox[2] * zoom),
                    int(bbox[3] * zoom)
                )

                # Crop the figure region
                cropped = img.crop(scaled_bbox)

                # Skip if too small after cropping
                if cropped.width < 100 or cropped.height < 100:
                    continue

                # Save figure
                figure_id = f"figure_{region['fig_num']}"
                image_filename = f"{figure_id}.png"
                image_path = figures_dir / image_filename
                cropped.save(image_path, "PNG", optimize=True)

                figures.append(Figure(
                    figure_id=figure_id,
                    page_number=region["page_num"] + 1,
                    bbox=bbox,
                    image_path=image_path,
                    caption=region.get("caption", "")
                ))

            except Exception as e:
                # Skip problematic figures
                continue

        doc.close()
        return figures

    def _find_figure_regions(self, doc: fitz.Document) -> list[dict]:
        """
        Find figure regions using hybrid approach:
        1. Find embedded images on each page
        2. Find figure captions
        3. Match images to captions by proximity
        4. Use image bounding boxes (more accurate than caption-based guessing)

        Args:
            doc: PyMuPDF document

        Returns:
            List of region dicts with page_num, fig_num, bbox, caption
        """
        regions = []
        # Strict caption pattern - must be start of block or have separator
        # Matches: "Figure 1 |", "Figure 1.", "Figure 1:", "Fig. 2 -"
        # Avoids: "see Figure 1 for", "in Figure 1, we"
        caption_pattern = re.compile(
            r"^(Figure|Fig\.?)\s+(\d+[a-zA-Z]?)\s*[\|\.\:\-]",
            re.IGNORECASE | re.MULTILINE
        )

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_width = page.rect.width
            page_height = page.rect.height

            # Step 1: Find all visual content (images + large drawings)
            visual_rects = []

            # Get embedded images
            for img in page.get_images():
                try:
                    xref = img[0]
                    rects = page.get_image_rects(xref)
                    for rect in rects:
                        if rect.width > 50 and rect.height > 50:
                            visual_rects.append(rect)
                except Exception:
                    continue

            # Get large drawings (vector graphics - common in academic papers)
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if rect and rect.width > 100 and rect.height > 100:
                    # Filter out full-page backgrounds
                    if rect.width < page_width * 0.95 or rect.height < page_height * 0.95:
                        visual_rects.append(rect)

            # Merge overlapping/adjacent rects into figure regions
            merged_rects = self._merge_image_rects(visual_rects)

            # Step 2: Find caption text blocks
            blocks = page.get_text("dict")["blocks"]
            captions = []

            for block in blocks:
                if block.get("type") != 0:
                    continue

                block_text = ""
                block_bbox = block.get("bbox", (0, 0, 0, 0))

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "")

                match = caption_pattern.search(block_text)
                if match:
                    fig_num = match.group(2)
                    caption_text = block_text[match.start():].strip()
                    captions.append({
                        "fig_num": fig_num,
                        "bbox": block_bbox,
                        "caption": caption_text,
                        "y_center": (block_bbox[1] + block_bbox[3]) / 2
                    })

            # Step 3: Match images to captions
            used_rects = set()

            for cap in captions:
                cap_y = cap["y_center"]
                best_rect = None
                best_distance = float('inf')

                # Find the closest image rect that's above the caption
                for i, rect in enumerate(merged_rects):
                    if i in used_rects:
                        continue

                    # Image should be above or overlapping with caption
                    rect_bottom = rect.y1
                    distance = abs(rect_bottom - cap["bbox"][1])

                    # Prefer images directly above caption
                    if rect_bottom <= cap["bbox"][1] + 50:  # Allow small overlap
                        if distance < best_distance:
                            best_distance = distance
                            best_rect = (i, rect)

                if best_rect:
                    idx, rect = best_rect
                    used_rects.add(idx)

                    # Use image rect with padding
                    padding = 10
                    regions.append({
                        "page_num": page_num,
                        "fig_num": cap["fig_num"],
                        "bbox": (
                            max(0, rect.x0 - padding),
                            max(0, rect.y0 - padding),
                            min(page_width, rect.x1 + padding),
                            min(page_height, rect.y1 + padding)
                        ),
                        "caption": cap["caption"]
                    })
                else:
                    # Fallback: no matching image, use area above caption
                    cap_bbox = cap["bbox"]
                    margin = 30
                    fig_height = min(cap_bbox[1] - margin, 300)
                    fig_height = max(fig_height, 100)

                    regions.append({
                        "page_num": page_num,
                        "fig_num": cap["fig_num"],
                        "bbox": (
                            margin,
                            max(cap_bbox[1] - fig_height, margin),
                            page_width - margin,
                            cap_bbox[1] - 5
                        ),
                        "caption": cap["caption"]
                    })

            # Step 4: Handle unmatched large images (figures without detected captions)
            for i, rect in enumerate(merged_rects):
                if i not in used_rects and rect.width > 200 and rect.height > 200:
                    # Large unmatched image - likely a figure
                    regions.append({
                        "page_num": page_num,
                        "fig_num": f"auto_{page_num}_{i}",
                        "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                        "caption": ""
                    })

        return regions

    def _merge_image_rects(
        self,
        rects: list,
        gap_threshold: float = 30
    ) -> list:
        """
        Merge nearby image rectangles that likely belong to the same figure.

        Args:
            rects: List of fitz.Rect objects
            gap_threshold: Maximum gap between rects to merge

        Returns:
            List of merged fitz.Rect objects
        """
        if not rects:
            return []

        # Sort by y position then x
        sorted_rects = sorted(rects, key=lambda r: (r.y0, r.x0))
        merged = []
        current = None

        for rect in sorted_rects:
            if current is None:
                current = fitz.Rect(rect)
            else:
                # Check if rects should be merged
                # Merge if they overlap or are close together
                expanded = fitz.Rect(
                    current.x0 - gap_threshold,
                    current.y0 - gap_threshold,
                    current.x1 + gap_threshold,
                    current.y1 + gap_threshold
                )

                if expanded.intersects(rect):
                    # Merge: expand current to include new rect
                    current = fitz.Rect(
                        min(current.x0, rect.x0),
                        min(current.y0, rect.y0),
                        max(current.x1, rect.x1),
                        max(current.y1, rect.y1)
                    )
                else:
                    merged.append(current)
                    current = fitz.Rect(rect)

        if current is not None:
            merged.append(current)

        return merged

    def _extract_large_images_fallback(
        self,
        doc: fitz.Document,
        figures_dir: Path
    ) -> list[Figure]:
        """
        Fallback extraction for PDFs without clear figure captions.
        Groups nearby images and extracts only large, significant images.

        Args:
            doc: PyMuPDF document
            figures_dir: Directory to save figure images

        Returns:
            List of Figure objects
        """
        figures = []
        figure_counter = 1
        min_dimension = 150  # Minimum width/height in pixels

        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images()

            # Collect all significant images on this page with their positions
            page_images = []
            for img in image_list:
                try:
                    xref = img[0]
                    img_rects = page.get_image_rects(xref)
                    if not img_rects:
                        continue

                    rect = img_rects[0]
                    width = rect.width
                    height = rect.height

                    # Skip small images
                    if width < min_dimension or height < min_dimension:
                        continue

                    page_images.append({
                        "xref": xref,
                        "rect": rect,
                        "area": width * height
                    })
                except Exception:
                    continue

            # Group overlapping/adjacent images
            grouped = self._group_nearby_images(page_images)

            # Render and extract each group
            for group in grouped:
                try:
                    # Calculate bounding box for the group
                    x0 = min(img["rect"].x0 for img in group)
                    y0 = min(img["rect"].y0 for img in group)
                    x1 = max(img["rect"].x1 for img in group)
                    y1 = max(img["rect"].y1 for img in group)

                    # Add padding
                    padding = 10
                    x0 = max(0, x0 - padding)
                    y0 = max(0, y0 - padding)
                    x1 = min(page.rect.width, x1 + padding)
                    y1 = min(page.rect.height, y1 + padding)

                    # Render this region
                    zoom = 2.0
                    mat = fitz.Matrix(zoom, zoom)
                    clip = fitz.Rect(x0, y0, x1, y1)
                    pix = page.get_pixmap(matrix=mat, clip=clip)

                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    # Skip if still too small
                    if img.width < 200 or img.height < 200:
                        continue

                    # Save figure
                    figure_id = f"figure_{figure_counter}"
                    image_filename = f"{figure_id}.png"
                    image_path = figures_dir / image_filename
                    img.save(image_path, "PNG", optimize=True)

                    figures.append(Figure(
                        figure_id=figure_id,
                        page_number=page_num + 1,
                        bbox=(x0, y0, x1, y1),
                        image_path=image_path,
                        caption=""
                    ))
                    figure_counter += 1

                except Exception:
                    continue

        return figures

    def _group_nearby_images(
        self,
        images: list[dict],
        threshold: float = 50
    ) -> list[list[dict]]:
        """
        Group images that are close together (likely parts of same figure).

        Args:
            images: List of image dicts with rect info
            threshold: Maximum distance to consider images as same group

        Returns:
            List of grouped image lists
        """
        if not images:
            return []

        # Sort by position (top-left)
        images = sorted(images, key=lambda x: (x["rect"].y0, x["rect"].x0))

        groups = []
        used = set()

        for i, img in enumerate(images):
            if i in used:
                continue

            group = [img]
            used.add(i)

            # Find nearby images
            for j, other in enumerate(images):
                if j in used:
                    continue

                # Check if rectangles are close
                r1, r2 = img["rect"], other["rect"]

                # Calculate distance between rectangles
                dx = max(0, max(r1.x0, r2.x0) - min(r1.x1, r2.x1))
                dy = max(0, max(r1.y0, r2.y0) - min(r1.y1, r2.y1))
                distance = (dx ** 2 + dy ** 2) ** 0.5

                if distance < threshold:
                    group.append(other)
                    used.add(j)

            groups.append(group)

        return groups

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

        Note: With page-rendering extraction, captions are already extracted
        during figure detection. This method only fills in missing captions.

        Args:
            full_text: Full text of the paper
            figures: List of extracted figures

        Returns:
            Updated list of figures with captions
        """
        # Skip if all figures already have captions
        if all(fig.caption for fig in figures):
            return figures

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

        # Match captions to figures that don't have one
        for figure in figures:
            if figure.caption:
                continue  # Already has caption from extraction

            # Extract figure number from figure_id (e.g., "figure_1" -> "1")
            fig_num = figure.figure_id.replace("figure_", "")
            if fig_num in captions:
                figure.caption = captions[fig_num]
            elif f"{fig_num}a" in captions:
                # Handle subfigures
                figure.caption = captions[f"{fig_num}a"]

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

    def parse_structured_caption(self, caption_text: str) -> StructuredCaption:
        """
        Parse a raw caption into structured format with title and sub-captions.

        Handles formats like:
        - "Title. (A) Description A. (B) Description B."
        - "Title. a, Description a; b, Description b"
        - "Title | (a) Desc a (b) Desc b"

        Args:
            caption_text: Raw caption text

        Returns:
            StructuredCaption with title and sub_captions
        """
        if not caption_text:
            return StructuredCaption(title="", sub_captions=[])

        # Clean up the text
        text = re.sub(r'\s+', ' ', caption_text).strip()

        # Pattern to match sub-figure labels: (A), (a), a), A., a.
        sub_pattern = re.compile(
            r'[\(\|]\s*([A-Za-z])\s*[\)\.\,\|]|'  # (A) or |A| or A) or A.
            r'\b([a-z])\s*[,;]\s+(?=[A-Z])',       # a, Description
            re.IGNORECASE
        )

        # Find all sub-caption markers
        matches = list(sub_pattern.finditer(text))

        if not matches:
            # No sub-captions found, entire text is the title
            return StructuredCaption(title=text, sub_captions=[])

        # Title is everything before the first sub-caption marker
        first_match = matches[0]
        title = text[:first_match.start()].strip()

        # Remove trailing punctuation from title
        title = re.sub(r'[\.\:\|\-]+$', '', title).strip()

        # Extract sub-captions
        sub_captions = []
        for i, match in enumerate(matches):
            label = match.group(1) or match.group(2)
            label = label.upper()  # Normalize to uppercase

            # Find the text for this sub-caption
            start = match.end()
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(text)

            sub_text = text[start:end].strip()
            # Clean up trailing punctuation before next label
            sub_text = re.sub(r'[\.\;\,\|]+$', '', sub_text).strip()

            if sub_text:
                sub_captions.append(SubCaption(label=label, text=sub_text))

        return StructuredCaption(title=title, sub_captions=sub_captions)

    def add_structured_captions(self, figures: list[Figure]) -> list[Figure]:
        """
        Parse raw captions into structured format for all figures.

        Args:
            figures: List of figures with raw captions

        Returns:
            Updated figures with structured_caption field populated
        """
        for figure in figures:
            if figure.caption and not figure.structured_caption:
                figure.structured_caption = self.parse_structured_caption(figure.caption)
        return figures

    def extract_figure_references(
        self,
        full_text: str,
        figures: list[Figure]
    ) -> list[Figure]:
        """
        Extract in-text references to figures and associate them with figures.

        Finds sentences like "As shown in Fig. 1A, the results..." and adds
        them to the corresponding figure's structured caption.

        Args:
            full_text: Full text of the paper
            figures: List of figures to update

        Returns:
            Updated figures with references populated
        """
        # Pattern to find figure references with surrounding context
        # Matches: Fig. 1, Figure 1A, Fig. 1a, Figs. 1-3, Figure 1 (A), etc.
        ref_pattern = re.compile(
            r'([^.]*?'  # Context before
            r'(?:Fig(?:ure|s)?\.?\s*'  # Figure/Fig./Figs.
            r'(\d+)\s*'  # Figure number
            r'([A-Za-z])?'  # Optional sub-label
            r'(?:\s*[-–]\s*\d+[A-Za-z]?)?'  # Optional range
            r'(?:\s*\([A-Za-z]\))?'  # Optional (A) format
            r')'
            r'[^.]*\.)',  # Context after until period
            re.IGNORECASE
        )

        # Track which page we're on based on page markers
        current_page = 1
        page_pattern = re.compile(r'--- Page (\d+) ---')

        # Split text by pages
        page_texts = re.split(r'--- Page \d+ ---', full_text)

        all_references: dict[str, list[FigureReference]] = {}

        for page_idx, page_text in enumerate(page_texts):
            page_num = page_idx  # 0-indexed, first split is before page 1

            for match in ref_pattern.finditer(page_text):
                sentence = match.group(0).strip()
                fig_num = match.group(2)
                sub_label = match.group(3) or ""

                # Clean up the sentence
                sentence = re.sub(r'\s+', ' ', sentence)

                # Create reference key (e.g., "1", "1A")
                ref_key = f"{fig_num}{sub_label.upper()}"

                if ref_key not in all_references:
                    all_references[ref_key] = []

                all_references[ref_key].append(FigureReference(
                    text=sentence,
                    page_number=page_num,
                    figure_label=ref_key
                ))

        # Associate references with figures
        for figure in figures:
            # Extract figure number from figure_id
            fig_num = figure.figure_id.replace("figure_", "")

            if figure.structured_caption is None:
                figure.structured_caption = StructuredCaption(title=figure.caption)

            # Add general figure references
            if fig_num in all_references:
                figure.structured_caption.references.extend(all_references[fig_num])

            # Add sub-figure specific references
            for sub_cap in figure.structured_caption.sub_captions:
                sub_key = f"{fig_num}{sub_cap.label.upper()}"
                if sub_key in all_references:
                    sub_cap.references.extend(all_references[sub_key])

        return figures

    async def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)

    def __del__(self):
        """Ensure cleanup on deletion."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)
