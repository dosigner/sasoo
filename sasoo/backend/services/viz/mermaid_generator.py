"""
Sasoo - Mermaid Diagram Generator

Uses Claude Sonnet 4.5 to convert VizRouter JSON targets into Mermaid code.
Supports flowchart, sequence, class, and state diagrams with styling based
on component types.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Style Palette
# ---------------------------------------------------------------------------

# Component-type -> fill color mapping for Mermaid style directives
_STYLE_PALETTE: dict[str, str] = {
    # Optical components
    "laser": "#e1f5fe",
    "source": "#e1f5fe",
    "detector": "#e8f5e9",
    "sensor": "#e8f5e9",
    "filter": "#fff3e0",
    "lens": "#f3e5f5",
    "mirror": "#f3e5f5",
    "collimator": "#f3e5f5",
    "beam_splitter": "#fce4ec",
    "bs": "#fce4ec",
    # Process steps
    "start": "#e8eaf6",
    "end": "#efebe9",
    "process": "#e0f2f1",
    "decision": "#fff9c4",
    "warning": "#ffebee",
    # Generic
    "input": "#e1f5fe",
    "output": "#e8f5e9",
    "chamber": "#fff3e0",
    "furnace": "#fff3e0",
    "substrate": "#f1f8e9",
    "precursor": "#e8eaf6",
    "default": "#f5f5f5",
}

# Mermaid diagram type templates
_DIAGRAM_TEMPLATES = {
    "flowchart": "graph {direction}",
    "sequence": "sequenceDiagram",
    "class": "classDiagram",
    "state": "stateDiagram-v2",
}


@dataclass
class MermaidOutput:
    """Result of a Mermaid generation."""
    title: str
    mermaid_code: str
    diagram_type: str = "flowchart"
    description: str = ""
    file_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "mermaid_code": self.mermaid_code,
            "diagram_type": self.diagram_type,
            "description": self.description,
            "file_path": self.file_path,
        }


# ---------------------------------------------------------------------------
# MermaidGenerator
# ---------------------------------------------------------------------------

class MermaidGenerator:
    """
    Generates Mermaid diagram code from VizRouter targets.

    Primary path: Claude Sonnet 4.5 converts structured JSON into polished
    Mermaid code with appropriate styling.

    Fallback path: local template-based generation when Claude is unavailable.
    """

    def __init__(self, claude_client: Any = None):
        """
        Args:
            claude_client: ClaudeClient instance for Sonnet 4.5 calls.
                          If None, uses local template-based generation.
        """
        self._claude = claude_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        viz_target: dict[str, Any],
        paper_dir: Optional[str] = None,
    ) -> MermaidOutput:
        """
        Generate Mermaid diagram code for a single viz target.

        Args:
            viz_target: VizTarget dict from the VizRouter.
            paper_dir: Directory to save the .md file. If None, no file is saved.

        Returns:
            MermaidOutput with the generated Mermaid code.
        """
        title = viz_target.get("title", "Diagram")
        diagram_type = viz_target.get("type", "flowchart")
        description = viz_target.get("description", "")

        # Try Claude-powered generation first
        mermaid_code: Optional[str] = None
        if self._claude is not None:
            try:
                mermaid_code = await self._generate_with_claude(viz_target)
            except Exception as exc:
                logger.warning(
                    "MermaidGenerator: Claude generation failed, using fallback: %s", exc
                )

        # Fallback to template-based generation
        if mermaid_code is None:
            mermaid_code = self._generate_from_template(viz_target)

        # Clean the code
        mermaid_code = self._clean_mermaid_code(mermaid_code)

        # Save to file if paper_dir is provided
        file_path: Optional[str] = None
        if paper_dir:
            file_path = self._save_to_file(
                mermaid_code=mermaid_code,
                title=title,
                description=description,
                paper_dir=paper_dir,
            )

        return MermaidOutput(
            title=title,
            mermaid_code=mermaid_code,
            diagram_type=diagram_type,
            description=description,
            file_path=file_path,
        )

    async def generate_batch(
        self,
        viz_targets: list[dict[str, Any]],
        paper_dir: Optional[str] = None,
    ) -> list[MermaidOutput]:
        """
        Generate Mermaid diagrams for multiple viz targets.

        Args:
            viz_targets: List of VizTarget dicts from the VizRouter.
            paper_dir: Directory to save .md files.

        Returns:
            List of MermaidOutput objects.
        """
        results: list[MermaidOutput] = []
        for target in viz_targets:
            try:
                output = await self.generate(target, paper_dir=paper_dir)
                results.append(output)
            except Exception as exc:
                logger.error(
                    "MermaidGenerator: Failed to generate diagram '%s': %s",
                    target.get("title", "?"), exc,
                )
        return results

    # ------------------------------------------------------------------
    # Claude-powered generation
    # ------------------------------------------------------------------

    async def _generate_with_claude(self, viz_target: dict[str, Any]) -> str:
        """
        Use Claude Sonnet 4.5 to generate polished Mermaid code.

        Delegates to ClaudeClient.generate_mermaid() which handles the full
        prompt construction, retry logic, and Mermaid extraction internally.
        """
        # Build the viz_json spec that ClaudeClient.generate_mermaid expects
        viz_json = {
            "viz_type": viz_target.get("type", "flowchart"),
            "title": viz_target.get("title", "Diagram"),
            "description": viz_target.get("description", ""),
            "data": {
                "nodes": viz_target.get("nodes", []),
                "edges": viz_target.get("edges", []),
                "category": viz_target.get("category", ""),
                "source": viz_target.get("source", {}),
            },
        }

        # ClaudeClient.generate_mermaid returns raw Mermaid code (no fences)
        mermaid_code = await self._claude.generate_mermaid(viz_json)
        return mermaid_code

    # ------------------------------------------------------------------
    # Template-based fallback generation
    # ------------------------------------------------------------------

    def _generate_from_template(self, viz_target: dict[str, Any]) -> str:
        """Generate Mermaid code from templates when Claude is unavailable."""
        diagram_type = viz_target.get("type", "flowchart")
        nodes = viz_target.get("nodes", [])
        edges = viz_target.get("edges", [])
        title = viz_target.get("title", "Diagram")

        if diagram_type in ("flowchart", "graph"):
            return self._build_flowchart(nodes, edges, title)
        elif diagram_type == "sequence":
            return self._build_sequence(nodes, edges, title)
        elif diagram_type == "state":
            return self._build_state_diagram(nodes, edges, title)
        elif diagram_type == "class":
            return self._build_class_diagram(nodes, edges, title)
        else:
            # Default to flowchart
            return self._build_flowchart(nodes, edges, title)

    def _build_flowchart(
        self,
        nodes: list[dict],
        edges: list[dict],
        title: str,
        direction: str = "LR",
    ) -> str:
        """Build a Mermaid flowchart from nodes and edges."""
        lines = [f"graph {direction}"]

        # Determine direction heuristic: if > 6 nodes, use TD
        if len(nodes) > 6:
            lines[0] = "graph TD"

        # Build node definitions
        style_lines: list[str] = []
        for node in nodes:
            node_id = self._sanitize_id(node.get("id", ""))
            label = self._escape_label(node.get("label", node_id))
            detail = node.get("detail", "")

            if detail:
                label = f"{label}<br/>{self._escape_label(detail)}"

            lines.append(f"    {node_id}[{label}]")

            # Assign style based on label keywords
            color = self._determine_node_color(node)
            style_lines.append(f"    style {node_id} fill:{color}")

        # Build edges
        for edge in edges:
            from_id = self._sanitize_id(edge.get("from", edge.get("from_id", "")))
            to_id = self._sanitize_id(edge.get("to", edge.get("to_id", "")))
            label = edge.get("label", "")

            if label and label != "sequential":
                lines.append(f"    {from_id} -->|{self._escape_label(label)}| {to_id}")
            else:
                lines.append(f"    {from_id} --> {to_id}")

        # If no edges but multiple nodes, create a sequential chain
        if not edges and len(nodes) > 1:
            for i in range(len(nodes) - 1):
                from_id = self._sanitize_id(nodes[i].get("id", ""))
                to_id = self._sanitize_id(nodes[i + 1].get("id", ""))
                lines.append(f"    {from_id} --> {to_id}")

        # Append style directives
        if style_lines:
            lines.append("")
            lines.extend(style_lines)

        return "\n".join(lines)

    def _build_sequence(
        self,
        nodes: list[dict],
        edges: list[dict],
        title: str,
    ) -> str:
        """Build a Mermaid sequence diagram."""
        lines = ["sequenceDiagram"]

        # Declare participants
        for node in nodes:
            node_id = self._sanitize_id(node.get("id", ""))
            label = node.get("label", node_id)
            lines.append(f"    participant {node_id} as {label}")

        # Build interactions from edges
        for edge in edges:
            from_id = self._sanitize_id(edge.get("from", edge.get("from_id", "")))
            to_id = self._sanitize_id(edge.get("to", edge.get("to_id", "")))
            label = edge.get("label", "")
            lines.append(f"    {from_id}->>+{to_id}: {label}")

        # If no edges, create sequential interactions
        if not edges and len(nodes) > 1:
            for i in range(len(nodes) - 1):
                from_id = self._sanitize_id(nodes[i].get("id", ""))
                to_id = self._sanitize_id(nodes[i + 1].get("id", ""))
                from_label = nodes[i].get("label", from_id)
                lines.append(f"    {from_id}->>+{to_id}: {from_label}")

        return "\n".join(lines)

    def _build_state_diagram(
        self,
        nodes: list[dict],
        edges: list[dict],
        title: str,
    ) -> str:
        """Build a Mermaid state diagram."""
        lines = ["stateDiagram-v2"]

        # Declare states
        for node in nodes:
            node_id = self._sanitize_id(node.get("id", ""))
            label = node.get("label", node_id)
            lines.append(f"    {node_id} : {label}")

        # Transitions
        if edges:
            for edge in edges:
                from_id = self._sanitize_id(edge.get("from", edge.get("from_id", "")))
                to_id = self._sanitize_id(edge.get("to", edge.get("to_id", "")))
                label = edge.get("label", "")
                if label:
                    lines.append(f"    {from_id} --> {to_id} : {label}")
                else:
                    lines.append(f"    {from_id} --> {to_id}")
        elif len(nodes) > 1:
            # Sequential states
            lines.append(f"    [*] --> {self._sanitize_id(nodes[0].get('id', ''))}")
            for i in range(len(nodes) - 1):
                from_id = self._sanitize_id(nodes[i].get("id", ""))
                to_id = self._sanitize_id(nodes[i + 1].get("id", ""))
                lines.append(f"    {from_id} --> {to_id}")
            lines.append(
                f"    {self._sanitize_id(nodes[-1].get('id', ''))} --> [*]"
            )

        return "\n".join(lines)

    def _build_class_diagram(
        self,
        nodes: list[dict],
        edges: list[dict],
        title: str,
    ) -> str:
        """Build a Mermaid class diagram."""
        lines = ["classDiagram"]

        for node in nodes:
            node_id = self._sanitize_id(node.get("id", ""))
            label = node.get("label", node_id)
            detail = node.get("detail", "")
            lines.append(f"    class {node_id} {{")
            lines.append(f"        +{label}")
            if detail:
                lines.append(f"        +{detail}")
            lines.append("    }")

        for edge in edges:
            from_id = self._sanitize_id(edge.get("from", edge.get("from_id", "")))
            to_id = self._sanitize_id(edge.get("to", edge.get("to_id", "")))
            label = edge.get("label", "")
            if label:
                lines.append(f"    {from_id} --> {to_id} : {label}")
            else:
                lines.append(f"    {from_id} --> {to_id}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sanitize_id(self, node_id: str) -> str:
        """Ensure a Mermaid-safe node ID."""
        if not node_id:
            return "X"
        # Replace non-alphanumeric chars with underscore
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
        # Ensure it starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = "N" + sanitized
        return sanitized or "X"

    def _escape_label(self, label: str) -> str:
        """Escape special Mermaid characters in labels."""
        if not label:
            return ""
        # Replace characters that break Mermaid syntax
        label = label.replace('"', "'")
        label = label.replace("#", "")
        label = label.replace(";", ",")
        # Keep <br/> for line breaks
        return label

    def _determine_node_color(self, node: dict) -> str:
        """Determine fill color based on node content."""
        label = (node.get("label", "") + " " + node.get("detail", "")).lower()

        for keyword, color in _STYLE_PALETTE.items():
            if keyword in label:
                return color

        return _STYLE_PALETTE["default"]

    def _clean_mermaid_code(self, code: str) -> str:
        """Strip markdown fences, frontmatter, and sanitize for Mermaid 10.x."""
        code = code.strip()

        # Remove markdown code fences
        if code.startswith("```mermaid"):
            code = code[len("```mermaid"):].strip()
        elif code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        # Remove --- frontmatter blocks (major source of "Syntax error in text")
        code = self._strip_frontmatter(code)

        # Remove accTitle / accDescr lines
        code = re.sub(r"^\s*accTitle\s*:.*$", "", code, flags=re.MULTILINE)
        code = re.sub(r"^\s*accDescr\s*:.*$", "", code, flags=re.MULTILINE)
        # Also remove multi-line accDescr blocks
        code = re.sub(
            r"^\s*accDescr\s*\{[^}]*\}",
            "",
            code,
            flags=re.MULTILINE | re.DOTALL,
        )

        # Fix unquoted labels with special characters in node definitions
        # Pattern: ID[label with (parens) or special chars]  ->  ID["label with (parens) or special chars"]
        code = self._fix_unquoted_labels(code)

        # Remove blank lines at the start
        code = code.strip()

        return code

    def _strip_frontmatter(self, code: str) -> str:
        """Remove YAML frontmatter block (---...---) from start of Mermaid code."""
        # Match frontmatter at the beginning: --- <anything> ---
        fm_pattern = re.compile(r"^\s*---\s*\n.*?\n\s*---\s*\n?", re.DOTALL)
        match = fm_pattern.match(code)
        if match:
            code = code[match.end():]
        return code

    def _fix_unquoted_labels(self, code: str) -> str:
        """
        Wrap unquoted node labels containing special characters in double quotes.

        Handles patterns like:
          A[레이저 (1064nm)]  ->  A["레이저 (1064nm)"]
          B{판단: 통과?}      ->  B{"판단: 통과?"}
        """
        # Characters that indicate the label needs quoting
        needs_quoting_chars = set("():<>;{}|&")

        def _quote_label(m: re.Match) -> str:
            prefix = m.group(1)   # node ID + opening bracket
            label = m.group(2)    # label text
            suffix = m.group(3)   # closing bracket

            # Already quoted — leave alone
            if label.startswith('"') and label.endswith('"'):
                return m.group(0)

            # Check if the label has characters that need quoting
            if any(c in needs_quoting_chars for c in label):
                # Escape existing double quotes inside the label
                label = label.replace('"', "'")
                return f'{prefix}"{label}"{suffix}'

            return m.group(0)

        # Match node definitions: ID[label], ID(label), ID{label}, ID([label]), ID[(label)]
        # Capture group 1: ID + opening bracket(s)
        # Capture group 2: label content (non-greedy)
        # Capture group 3: closing bracket(s)
        patterns = [
            # Standard: A[label] or A["label"]
            (r'(\b\w+\[)((?:[^\[\]]|\n)*?)(\])', r'\1\2\3'),
            # Round: A(label) or A("label")
            (r'(\b\w+\()((?:[^()]|\n)*?)(\))', r'\1\2\3'),
            # Diamond: A{label} or A{"label"}
            (r'(\b\w+\{)((?:[^{}]|\n)*?)(\})', r'\1\2\3'),
        ]

        for pattern, _repl in patterns:
            code = re.sub(pattern, _quote_label, code)

        return code

    def _save_to_file(
        self,
        mermaid_code: str,
        title: str,
        description: str,
        paper_dir: str,
    ) -> str:
        """Save Mermaid code as a .md file in the paper's mermaid/ directory."""
        mermaid_dir = Path(paper_dir) / "mermaid"
        mermaid_dir.mkdir(parents=True, exist_ok=True)

        # Build a safe filename
        safe_title = re.sub(r"[^\w\s-]", "", title).strip()
        safe_title = re.sub(r"[-\s]+", "_", safe_title).lower()
        if not safe_title:
            safe_title = "diagram"

        file_path = mermaid_dir / f"{safe_title}.md"

        # Avoid overwriting: append a counter
        counter = 1
        while file_path.exists():
            file_path = mermaid_dir / f"{safe_title}_{counter}.md"
            counter += 1

        content = f"# {title}\n\n"
        if description:
            content += f"> {description}\n\n"
        content += f"```mermaid\n{mermaid_code}\n```\n"

        file_path.write_text(content, encoding="utf-8")
        logger.info("MermaidGenerator: Saved diagram to %s", file_path)

        return str(file_path)
