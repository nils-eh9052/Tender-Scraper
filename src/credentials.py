"""
Credential manager for portal logins.

Loads from environment variables set in .env:
  UK_DSP_USERNAME / UK_DSP_PASSWORD
  DE_EVERGABE_USERNAME / DE_EVERGABE_PASSWORD
  etc.

Never hardcode credentials in source files.
"""
import os


class CredentialManager:
    """Load portal credentials from environment variables."""

    @staticmethod
    def get(portal: str) -> dict:
        """
        Return {'username': ..., 'password': ...} if configured, else {}.

        portal:  upper-snake-cased prefix, e.g. 'UK_DSP', 'DE_EVERGABE'.
        """
        prefix = portal.upper().replace("-", "_")
        username = os.environ.get(f"{prefix}_USERNAME", "").strip()
        password = os.environ.get(f"{prefix}_PASSWORD", "").strip()
        if username and password:
            return {"username": username, "password": password}
        return {}

    @staticmethod
    def has(portal: str) -> bool:
        """Return True if credentials are configured for this portal."""
        return bool(CredentialManager.get(portal))
