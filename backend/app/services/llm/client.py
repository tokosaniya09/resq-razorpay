"""The single LLM boundary for the whole system.

Every AI feature — customer outreach, degradation root-cause diagnosis, and
merchant escalation notes — calls the model through this one client. That
matters for two reasons:

1.  Isolation. There is exactly one place in the codebase that talks to an
    LLM. The deterministic money path never imports it. If you want to prove
    "AI touches no money decision," you point at this file and its callers —
    all of which consume *text*, none of which decide or move money.

2.  Swappability. The provider (Gemini / Anthropic / ...) is a config value.
    Adding a provider is a new private method here; nothing else changes.

Every call is best-effort: `complete()` returns None on any failure (missing
key, rate limit, network blip), and every caller has a deterministic fallback.
So the LLM being unavailable degrades gracefully — it never breaks recovery.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger("resq.llm")


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def enabled(self) -> bool:
        return self._s.llm_enabled and self._s.llm_provider != "template"

    def complete(self, system: str, prompt: str, max_tokens: int = 200) -> str | None:
        """Return model text, or None on any failure. Never raises."""
        if not self.enabled:
            return None
        try:
            if self._s.llm_provider == "gemini":
                return self._gemini(system, prompt, max_tokens)
            if self._s.llm_provider == "anthropic":
                return self._anthropic(system, prompt, max_tokens)
            log.warning("Unknown llm_provider '%s'; using fallback", self._s.llm_provider)
            return None
        except Exception as exc:  # noqa: BLE001 - best-effort by design
            # Full detail so a misconfigured key/model/dependency is diagnosable
            # in the backend logs, while still falling back gracefully.
            log.warning(
                "LLM call failed (provider=%s model=%s): %r; falling back to "
                "deterministic/template.",
                self._s.llm_provider,
                self._s.llm_model,
                exc,
            )
            return None

    # -- providers ---------------------------------------------------------- #
    def _gemini(self, system: str, prompt: str, max_tokens: int) -> str | None:
        # Free tier via Google AI Studio. Imported lazily so the dependency is
        # only needed when Gemini is actually the selected provider.
        import google.generativeai as genai

        genai.configure(api_key=self._s.llm_api_key)
        model = genai.GenerativeModel(
            model_name=self._s.llm_model,
            system_instruction=system,
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.5},
        )
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None)
        return text.strip() if text else None

    def _anthropic(self, system: str, prompt: str, max_tokens: int) -> str | None:
        import anthropic

        client = anthropic.Anthropic(api_key=self._s.llm_api_key)
        msg = client.messages.create(
            model=self._s.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip() or None