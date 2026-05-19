"""Quick env-check: ruft load_env_chain auf und zeigt geladene Files + Keys.

Run from ted-scraper/ted-scraper/ root:
    python3 scripts/_check_env.py
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.env_loader import load_env_chain

loaded = load_env_chain()

print("Geladene Dateien:")
if loaded:
    for p in loaded:
        print(f"  - {p}")
else:
    print("  (keine .env oder .env.local gefunden)")

print()
print("Key-Check:")
key = os.environ.get("LLM_OPENROUTER_API_KEY", "")
if key:
    print(f"  LLM_OPENROUTER_API_KEY: {key[:25]}...")
else:
    print("  LLM_OPENROUTER_API_KEY: (FEHLT)")

print(f"  LLM_MODEL_NAME:         {os.environ.get('LLM_MODEL_NAME', '(FEHLT)')}")
print(f"  SSL_VERIFY_DISABLE:     {os.environ.get('SSL_VERIFY_DISABLE', '(FEHLT)')}")
print(f"  UK_DSP_USERNAME:        {os.environ.get('UK_DSP_USERNAME', '(FEHLT)')}")
print(f"  DE_EVERGABE_USERNAME:   {os.environ.get('DE_EVERGABE_USERNAME', '(FEHLT)')}")
