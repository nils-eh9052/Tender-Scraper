"""
National portal fallback — Phase 3g extension.

Triggered when tender_documents_access URL is missing or dead (404/timeout/0-byte).
Supported countries: DE, PL, CZ.

Each module returns:
    {
        "portal_url": str,
        "documents": List[DocumentRef],
        "additional_fields": {
            "winner": str,
            "quantity": int | None,
            "contract_duration": str,
            "value": float | None,
        }
    }
    or None if nothing found.
"""
from .de_search import search_de
from .pl_search import search_pl
from .cz_search import search_cz

__all__ = ["search_de", "search_pl", "search_cz"]
