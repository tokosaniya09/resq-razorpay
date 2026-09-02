"""Application configuration.

Every threshold and safety limit lives here (backed by environment variables)
rather than being hard-coded in the logic. Two reasons this matters:

1.  During the demo we can tune degradation thresholds live without touching
    code — required by the design doc (§6.3).
2.  The guardrail limits (retry cap, cooldown, link TTL, amount cap) are the
    safety contract of the whole system. Keeping them in one auditable place
    is how a reviewer verifies "money actions are bounded" at a glance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env by ABSOLUTE path so it loads no matter which directory uvicorn
# is started from (a relative "env_file" is resolved against the current working
# directory, which is a common cause of "my .env is ignored"). We look in the
# backend folder and the repo root; if both exist, the backend one wins.
_BACKEND_DIR = Path(__file__).resolve().parents[2]   # .../backend
_REPO_ROOT = _BACKEND_DIR.parent                     # repo root
_ENV_FILES = (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    # ---- App ----
    app_name: str = "ResQ-Pay"
    environment: str = "development"
    database_url: str = "sqlite:///./resq_pay.db"

    # ---- Razorpay (Test Mode only — see Non-Goal N1) ----
    # If keys are absent, the client runs in MOCK mode and no network is used.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_mock: bool = True  # default to mock so it runs clone-and-go

    # ---- Degradation detector (§6.3) — all tunable at runtime ----
    degradation_window_size: int = 20          # events per route in the rolling window
    degradation_min_samples: int = 5           # don't judge health on too little data
    degradation_warn_threshold: float = 0.40   # >=40% failures -> DEGRADING
    degradation_critical_threshold: float = 0.65  # >=65% failures -> DOWN
    recovering_threshold: float = 0.25         # fail rate must drop below this to recover
    recovering_drain_after_seconds: int = 8    # dwell in RECOVERING before HEALTHY

    # ---- Guardrails (§6.5) — the safety contract ----
    max_retry_attempts: int = 2                # per transaction identifier
    retry_cooldown_seconds: int = 5            # rule-based, NOT ML (Non-Goal N3)
    recovery_link_ttl_minutes: int = 15
    recovery_link_amount_cap_paise: int = 50_000_00  # ₹50,000 hard ceiling

    # ---- Outreach / LLM (§6.7) ----
    llm_enabled: bool = False                  # off by default -> template fallback
    llm_provider: str = "gemini"               # "template" | "gemini" | "anthropic"
    llm_api_key: str | None = None
    llm_model: str = "gemini-3.6-flash"        # free tier via Google AI Studio
    # "en" = template only (no LLM); set e.g. "Hinglish" to translate via LLM
    outreach_language: str = "en"

    @property
    def retry_cooldown(self) -> int:
        return self.retry_cooldown_seconds


@lru_cache
def get_settings() -> Settings:
    return Settings()
