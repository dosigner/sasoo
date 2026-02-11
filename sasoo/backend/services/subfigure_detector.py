"""
Sub-figure detection service using Gemini Vision.

Analyzes composite figures and identifies individual sub-figure boundaries
for papers like Nature that have Figure 1(A), (B), (C) etc.
"""
import base64
import json
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from PIL import Image
import io

from services.llm.gemini_client import GeminiClient, MODEL_FLASH
from models.paper import Figure, StructuredCaption, SubCaption


@dataclass
class SubFigureBoundary:
    """Detected sub-figure boundary within a composite figure."""
    label: str  # "A", "B", "C" etc.
    bbox: tuple[float, float, float, float]  # Relative coordinates (0-1)
    description: str  # Brief description of what this sub-figure shows


@dataclass
class SubFigureDetectionResult:
    """Result of sub-figure detection on a single figure."""
    figure_id: str
    has_subfigures: bool
    subfigures: list[SubFigureBoundary]
    layout: str  # "horizontal", "vertical", "grid", "single"
    confidence: float  # 0-1
    raw_response: str  # For debugging


class SubFigureDetector:
    """
    Detects and extracts sub-figures from composite figures using Gemini Vision.
    """

    DETECTION_PROMPT = """Analyze this scientific figure image and identify any sub-figures.

Many scientific papers (especially Nature, Science, Cell) have composite figures with labeled panels like (A), (B), (C) or (a), (b), (c).

Tasks:
1. Determine if this is a composite figure with multiple panels
2. If yes, identify each panel's label and bounding box
3. Describe the layout (horizontal row, vertical stack, grid, or single)

Respond in JSON format ONLY:
```json
{
  "has_subfigures": true/false,
  "layout": "horizontal" | "vertical" | "grid" | "single",
  "confidence": 0.0-1.0,
  "subfigures": [
    {
      "label": "A",
      "bbox": [x_min, y_min, x_max, y_max],
      "description": "Brief description"
    }
  ]
}
```

Bounding box coordinates should be RELATIVE (0.0 to 1.0), where:
- (0, 0) is top-left corner
- (1, 1) is bottom-right corner

If no sub-figures are detected, return:
```json
{
  "has_subfigures": false,
  "layout": "single",
  "confidence": 0.95,
  "subfigures": []
}
```"""

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        """
        Initialize the sub-figure detector.

        Args:
            gemini_client: Optional pre-configured Gemini client
        """
        self._gemini_client = gemini_client
        self._owns_client = False

    async def _get_client(self) -> GeminiClient:
        """Get or create Gemini client."""
        if self._gemini_client is None:
            self._gemini_client = GeminiClient()
            self._owns_client = True
        return self._gemini_client

    async def detect_subfigures(
        self,
        figure: Figure
    ) -> SubFigureDetectionResult:
        """
        Detect sub-figures in a composite figure image.

        Args:
            figure: Figure object with image_path

        Returns:
            SubFigureDetectionResult with detected boundaries
        """
        client = await self._get_client()

        # Read and encode image
        image_path = Path(figure.image_path)
        if not image_path.exists():
            return SubFigureDetectionResult(
                figure_id=figure.figure_id,
                has_subfigures=False,
                subfigures=[],
                layout="single",
                confidence=0.0,
                raw_response="Image file not found"
            )

        # Load image and convert to base64
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # Get image dimensions for later conversion
        with Image.open(image_path) as img:
            img_width, img_height = img.size

        # Call Gemini with vision
        try:
            response = await client.generate_with_image(
                prompt=self.DETECTION_PROMPT,
                image_base64=image_base64,
                image_mime_type="image/png",
                model=MODEL_FLASH,  # Fast and cheap for this task
                phase="subfigure_detection"
            )

            # Parse JSON response
            result = self._parse_response(response, figure.figure_id)
            return result

        except Exception as e:
            return SubFigureDetectionResult(
                figure_id=figure.figure_id,
                has_subfigures=False,
                subfigures=[],
                layout="single",
                confidence=0.0,
                raw_response=f"Error: {str(e)}"
            )

    def _parse_response(
        self,
        response: str,
        figure_id: str
    ) -> SubFigureDetectionResult:
        """Parse Gemini response into structured result."""
        try:
            # Extract JSON from response (might have markdown code blocks)
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to parse as raw JSON
                json_str = response.strip()

            data = json.loads(json_str)

            subfigures = []
            for sf in data.get("subfigures", []):
                bbox = sf.get("bbox", [0, 0, 1, 1])
                subfigures.append(SubFigureBoundary(
                    label=sf.get("label", "?"),
                    bbox=tuple(bbox),
                    description=sf.get("description", "")
                ))

            return SubFigureDetectionResult(
                figure_id=figure_id,
                has_subfigures=data.get("has_subfigures", False),
                subfigures=subfigures,
                layout=data.get("layout", "single"),
                confidence=data.get("confidence", 0.5),
                raw_response=response
            )

        except json.JSONDecodeError:
            return SubFigureDetectionResult(
                figure_id=figure_id,
                has_subfigures=False,
                subfigures=[],
                layout="single",
                confidence=0.0,
                raw_response=f"JSON parse error: {response[:500]}"
            )

    async def extract_subfigures(
        self,
        figure: Figure,
        output_dir: Path,
        detection_result: Optional[SubFigureDetectionResult] = None
    ) -> list[Figure]:
        """
        Extract sub-figures as separate images based on detection result.

        Args:
            figure: Original composite figure
            output_dir: Directory to save sub-figure images
            detection_result: Optional pre-computed detection result

        Returns:
            List of Figure objects for each sub-figure
        """
        if detection_result is None:
            detection_result = await self.detect_subfigures(figure)

        if not detection_result.has_subfigures:
            return [figure]  # Return original if no sub-figures

        # Load original image
        image_path = Path(figure.image_path)
        with Image.open(image_path) as img:
            width, height = img.size

            extracted_figures = []
            for sf in detection_result.subfigures:
                # Convert relative bbox to absolute pixels
                x1 = int(sf.bbox[0] * width)
                y1 = int(sf.bbox[1] * height)
                x2 = int(sf.bbox[2] * width)
                y2 = int(sf.bbox[3] * height)

                # Ensure valid bounds
                x1, x2 = max(0, x1), min(width, x2)
                y1, y2 = max(0, y1), min(height, y2)

                if x2 <= x1 or y2 <= y1:
                    continue  # Invalid crop

                # Crop sub-figure
                cropped = img.crop((x1, y1, x2, y2))

                # Save sub-figure
                sub_id = f"{figure.figure_id}{sf.label.lower()}"
                sub_filename = f"{sub_id}.png"
                sub_path = output_dir / sub_filename
                cropped.save(sub_path, "PNG", optimize=True)

                # Create Figure object for sub-figure
                # Get sub-caption if available
                sub_caption = ""
                if figure.structured_caption:
                    for sc in figure.structured_caption.sub_captions:
                        if sc.label.upper() == sf.label.upper():
                            sub_caption = sc.text
                            break

                extracted_figures.append(Figure(
                    figure_id=sub_id,
                    page_number=figure.page_number,
                    bbox=(x1, y1, x2, y2),
                    image_path=sub_path,
                    caption=sub_caption or sf.description,
                    parent_figure_id=figure.figure_id,
                    sub_label=sf.label
                ))

            return extracted_figures

    async def close(self):
        """Cleanup resources."""
        if self._owns_client and self._gemini_client:
            # GeminiClient doesn't have async close, but we can clean up
            self._gemini_client = None
