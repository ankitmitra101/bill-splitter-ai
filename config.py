"""Application configuration for the Fair Split app.

Handles environment variable loading, API credentials, model selection,
and retry policies. Contains zero business logic.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

class Config:
    # ── Gemini API Configuration ──────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # ── Model Selection ───────────────────────────────────────────────────
    # We use gemini-2.5-flash by default as confirmed in the architecture phase.
    # It provides the optimal balance of speed and structured JSON capabilities.
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Temperature is strictly 0.0 to maximize determinism in OCR and parsing.
    GEMINI_TEMPERATURE: float = float(os.getenv("GEMINI_TEMPERATURE", "0.0"))
    
    # ── Retry Configuration ───────────────────────────────────────────────
    # Configuration for transient network or API errors during LLM calls.
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF_FACTOR: float = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))

config = Config()
