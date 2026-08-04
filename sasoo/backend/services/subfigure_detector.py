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

from services.llm.interactions_client import call_interaction
from services.model_registry import resolve as resolve_model
from models.paper import Figure

_SUBFIGURE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "has_subfigures": {"type": "boolean"},
        "layout": {"type": "string", "enum": ["horizontal", "vertical", "grid", "single"]},
        "confidence": {"type": "number"},
        "subfigures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "description": {"type": "string"},
                },
                "required": ["label", "bbox", "description"],
            },
        },
    },
    "required": ["has_subfigures", "layout", "confidence", "subfigures"],
}


# 패널 라벨은 관용적으로 한 글자(A/a) 또는 한두 자리 숫자다. 괄호·마침표는 벗겨낸다.
# 예: "A", "(b)", "c.", "1", "(2)" -> 통과 / "ASD PR CURVES (LEFT)", "TABLE 2" -> 탈락.
_SUB_LABEL_PATTERN = re.compile(r"^\(?\s*([A-Za-z]|\d{1,2})\s*[).\]]?$")

# 한 그림에서 뽑을 수 있는 패널 수 상한. 이걸 넘기면 패널 분해가 아니라 오검출로 본다.
MAX_SUBFIGURES = 12


def _normalize_sub_label(raw: str | None) -> Optional[str]:
    """모델이 준 라벨을 패널 라벨로 정규화한다. 패널 라벨이 아니면 None.

    검증이 없던 시절에는 모델이 돌려준 문자열이 그대로 figure_num에 이어붙어
    "Fig. 8ASD PR CURVES (LEFT)", "Fig. 7TABLE 2" 같은 항목이 갤러리에 쌓였다
    (실측: 한 논문에서 부모 8개에 서브피겨 25개, 그중 19개가 이런 형태).
    모델이 패널 라벨 대신 내용을 서술했다는 건 그 그림에 (a)(b)(c) 마커가 없다는
    뜻이므로, 그런 분해는 받아들이지 않는다.
    """
    if not raw:
        return None
    match = _SUB_LABEL_PATTERN.match(raw.strip())
    if not match:
        return None
    return match.group(1).upper()


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

        # Call Gemini with vision via the Interactions API
        try:
            _choice = resolve_model("subfigure", "gemini")
            result = await call_interaction(
                [
                    {"type": "image", "data": image_base64, "mime_type": "image/png"},
                    {"type": "text", "text": self.DETECTION_PROMPT},
                ],
                lane="pipeline",
                model=_choice.model,
                thinking_level=_choice.effort,
                store=False,
                response_schema=_SUBFIGURE_RESPONSE_SCHEMA,
            )

            # Parse JSON response
            return self._parse_response(result["text"], figure.figure_id)

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

            raw_subfigures = data.get("subfigures", []) or []
            subfigures = []
            rejected = 0
            for sf in raw_subfigures:
                label = _normalize_sub_label(sf.get("label"))
                if label is None:
                    rejected += 1
                    continue
                bbox = sf.get("bbox", [0, 0, 1, 1])
                subfigures.append(SubFigureBoundary(
                    label=label,
                    bbox=tuple(bbox),
                    description=sf.get("description", "")
                ))

            has_subfigures = bool(data.get("has_subfigures", False)) and bool(subfigures)
            # 라벨이 하나도 패널 라벨이 아니면(모델이 내용을 서술했다면) 분해를 통째로 버린다.
            # 부분적으로만 유효하면 유효한 것만 남긴다.
            # 상한을 넘는 분해는 패널 나누기가 아니라 오검출로 보고 역시 버린다.
            if rejected and not subfigures:
                has_subfigures = False
            if len(subfigures) > MAX_SUBFIGURES:
                has_subfigures = False
                subfigures = []

            return SubFigureDetectionResult(
                figure_id=figure_id,
                has_subfigures=has_subfigures,
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
