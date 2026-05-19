"""Document Extraction Pipeline — Phase 3g

Discovers, downloads, extracts and AI-structures procurement documents for each
notice in relevant.json.

Main entry point: orchestrator.run_extraction()
"""

from .discovery import DocumentRef, discover_for_notice
from .orchestrator import run_extraction
from .ai_structurer import active_model, cache_slug

__all__ = ["DocumentRef", "discover_for_notice", "run_extraction", "active_model", "cache_slug"]
