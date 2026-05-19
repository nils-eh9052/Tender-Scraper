"""Workspace-aware .env loader for the ted-scraper pipeline.

Lookup chain (highest priority first; later files DON'T overwrite):

  1. Already-set environment variables  — never overwritten
     (e.g. shell exports, CI secrets, ``SSL_VERIFY_DISABLE=1 python …``)
  2. <repo_root>/.env                   — local overrides, optional
  3. <workspace_root>/.env.local        — workspace-wide defaults

Where:
  repo_root      = ted-scraper/ted-scraper/      (folder containing main.py)
  workspace_root = 02_Tender Radar/              (two levels above repo_root)

The chain implements *setdefault* semantics: a key that's already in
``os.environ`` (whether from the shell or from an earlier file) is left
untouched. This means repo-local ``.env`` wins over workspace-root
``.env.local`` on conflicts, and shell exports win over everything.

Empty values (``LLM_OPENROUTER_API_KEY=``) are ignored — they would
shadow a real value defined later in the chain, which is rarely desired.

Typical use::

    from src.env_loader import load_env_chain
    load_env_chain()   # call ONCE at process start, before anything else
                       # reads os.environ
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


def _parse_env_file(path: Path) -> Iterator[tuple[str, str]]:
    """Yield (key, value) pairs from a dotenv-style file.

    Skips blank lines and ``# comments``. Strips surrounding single or
    double quotes. Does not handle multi-line values — those are uncommon
    in pipeline configs.
    """
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key:
            yield key, val


def load_env_chain(repo_root: Path | None = None) -> list[Path]:
    """Load .env files into ``os.environ`` with setdefault semantics.

    Args:
      repo_root: defaults to the folder two levels up from this file,
                 i.e. ``ted-scraper/ted-scraper/``. Override only for
                 testing.

    Returns:
      A list of the files actually read, in load order. Useful for
      logging which sources contributed to the runtime config.
    """
    if repo_root is None:
        # env_loader.py lives in <repo_root>/src/
        repo_root = Path(__file__).resolve().parent.parent
    workspace_root = repo_root.parent.parent

    loaded: list[Path] = []
    # Order matters: repo-local first (higher priority via setdefault),
    # then workspace-wide defaults (lower priority).
    for path in (repo_root / ".env", workspace_root / ".env.local"):
        if not path.exists():
            continue
        for key, val in _parse_env_file(path):
            if val and not os.environ.get(key):
                os.environ[key] = val
        loaded.append(path)
    return loaded
