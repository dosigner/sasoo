"""
Data models for the Sasoo backend.
"""

# Lazy imports to avoid circular dependency issues.
# Use: from models.paper import ParsedPaper, Figure, Table, Metadata
# Use: from models.schemas import PaperResponse, AnalysisStatus, etc.

__all__ = ["ParsedPaper", "Figure", "Table", "Metadata"]
