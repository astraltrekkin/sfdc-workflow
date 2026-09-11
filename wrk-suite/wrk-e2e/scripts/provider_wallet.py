#!/usr/bin/env python3
"""Live provider wallet / credits checks for wrk-begin Provider: Yes.

``ctl check-provider-wallet`` runs these checkers. Agents must not invent
``funded`` — only this module writes wallet verdicts. Never print secrets.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------------------
# Messaging / special-app — not wallets (credentials + live-use gates own these)
# --------------------------------------------------------------------------------------
NON_WALLET_PROVIDERS = frozenset(
    {
        "discord",
        "slack",
        "telegram",
        "whatsapp",
        "matrix",
    }
)

# Canonical name -> aliases that normalize to it.
_ALIASES: dict[str, str] = {
    "openai-codex": "openai",
    "claude": "anthropic",
    "gemini": "google",
    "zen": "opencode-zen",
    "nousresearch": "nous",
}

# Env var(s) for each inference provider (first non-empty wins when checking).
_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "xai": ("XAI_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "cohere": ("COHERE_API_KEY",),
    "opencode-zen": ("OPENCODE_ZEN_API_KEY",),
    "opencode-go": ("OPENCODE_GO_API_KEY",),
    "nous": ("NOUS_API_KEY",),
}

VERDICT_FUNDED = "funded"
VERDICT_TOP_UP = "top-up"
VERDICT_UNKNOWN = "unknown"
VERDICT_SKIP = "skip"  # messaging / non-wallet


def normalize_provider_name(raw: str) -> str:
    n = (raw or "").strip().lower()
    return _ALIASES.get(n, n)


def _min_remaining() -> float:
    raw = (os.environ.get("WRK_PROVIDER_WALLET_MIN_USD") or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _env_present(keys: tuple[str, ...]) -> bool:
    for k in keys:
        if (os.environ.get(k) or "").strip():
            return True
    return False


def _first_env(keys: tuple[str, ...]) -> str:
    for k in keys:
        val = (os.environ.get(k) or "").strip()
        if val:
            return val
    return ""


def _check_openrouter() -> dict[str, Any]:
    """GET https://openrouter.ai/api/v1/credits — remaining = total_credits - total_usage."""
    keys = _ENV_KEYS["openrouter"]
    if not _env_present(keys):
        return {
            "provider": "openrouter",
            "verdict": VERDICT_UNKNOWN,
            "reason": "missing OPENROUTER_API_KEY",
            "remaining": None,
        }
    token = _first_env(keys)
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {
            "provider": "openrouter",
            "verdict": VERDICT_UNKNOWN,
            "reason": f"credits API HTTP {e.code}",
            "remaining": None,
        }
    except Exception as e:
        return {
            "provider": "openrouter",
            "verdict": VERDICT_UNKNOWN,
            "reason": f"credits API error: {type(e).__name__}",
            "remaining": None,
        }

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {
            "provider": "openrouter",
            "verdict": VERDICT_UNKNOWN,
            "reason": "credits API returned non-JSON",
            "remaining": None,
        }

    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        payload = data if isinstance(data, dict) else {}
    try:
        total = float(payload.get("total_credits") or 0)
        usage = float(payload.get("total_usage") or 0)
        remaining = total - usage
    except (TypeError, ValueError):
        return {
            "provider": "openrouter",
            "verdict": VERDICT_UNKNOWN,
            "reason": "credits API missing total_credits/total_usage",
            "remaining": None,
        }

    floor = _min_remaining()
    if remaining > floor:
        return {
            "provider": "openrouter",
            "verdict": VERDICT_FUNDED,
            "reason": "credits remaining above floor",
            "remaining": remaining,
        }
    return {
        "provider": "openrouter",
        "verdict": VERDICT_TOP_UP,
        "reason": "credits remaining at or below floor — top-up needed",
        "remaining": remaining,
    }


def _anthropic_billing_exhausted(status: int, body: str) -> bool:
    """True when Anthropic rejects the call for empty credits / spend cap."""
    if status == 402:
        return True
    msg = ""
    etype = ""
    try:
        data = json.loads(body) if body else {}
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            etype = str(err.get("type") or "")
            msg = str(err.get("message") or "").lower()
    except json.JSONDecodeError:
        msg = (body or "").lower()
    if etype == "billing_error":
        return True
    needles = (
        "credit balance is too low",
        "credit balance",
        "purchase credits",
        "plans & billing",
        "monthly spend limit",
        "spend limit reached",
        "spend cap",
    )
    return any(n in msg for n in needles)


def _check_anthropic() -> dict[str, Any]:
    """
    Anthropic has no public prepaid-balance API (Admin cost reports are spend
    history only). Probe with a minimal Messages call; billing/credit errors
    → top-up; success → funded (remaining unknown).
    """
    keys = _ENV_KEYS["anthropic"]
    if not _env_present(keys):
        return {
            "provider": "anthropic",
            "verdict": VERDICT_UNKNOWN,
            "reason": "missing ANTHROPIC_API_KEY",
            "remaining": None,
        }
    token = _first_env(keys)
    model = (
        (os.environ.get("WRK_ANTHROPIC_PROBE_MODEL") or "").strip()
        or "claude-haiku-4-5-20251001"
    )
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        if _anthropic_billing_exhausted(e.code, err_body):
            return {
                "provider": "anthropic",
                "verdict": VERDICT_TOP_UP,
                "reason": "messages probe: credit/billing exhausted — top-up needed",
                "remaining": None,
            }
        if e.code == 401:
            return {
                "provider": "anthropic",
                "verdict": VERDICT_UNKNOWN,
                "reason": "messages probe HTTP 401 (invalid ANTHROPIC_API_KEY)",
                "remaining": None,
            }
        # Rate limits / overload still imply billing accepted the account.
        if e.code in (429, 529):
            return {
                "provider": "anthropic",
                "verdict": VERDICT_FUNDED,
                "reason": f"messages probe HTTP {e.code} (wallet ok; capacity/limit)",
                "remaining": None,
            }
        return {
            "provider": "anthropic",
            "verdict": VERDICT_UNKNOWN,
            "reason": f"messages probe HTTP {e.code}",
            "remaining": None,
        }
    except Exception as e:
        return {
            "provider": "anthropic",
            "verdict": VERDICT_UNKNOWN,
            "reason": f"messages probe error: {type(e).__name__}",
            "remaining": None,
        }

    return {
        "provider": "anthropic",
        "verdict": VERDICT_FUNDED,
        "reason": "messages probe ok (no USD balance API; remaining unknown)",
        "remaining": None,
    }


def _unknown_no_checker(canonical: str) -> dict[str, Any]:
    env_keys = _ENV_KEYS.get(canonical, ())
    if env_keys and not _env_present(env_keys):
        return {
            "provider": canonical,
            "verdict": VERDICT_UNKNOWN,
            "reason": f"missing {' / '.join(env_keys)}; no live wallet checker",
            "remaining": None,
        }
    if not env_keys:
        return {
            "provider": canonical,
            "verdict": VERDICT_UNKNOWN,
            "reason": "no wallet checker / no injected billing token",
            "remaining": None,
        }
    return {
        "provider": canonical,
        "verdict": VERDICT_UNKNOWN,
        "reason": "no wallet checker for this provider; do not guess",
        "remaining": None,
    }


CheckerFn = Callable[[], dict[str, Any]]

def _nous_bearers() -> list[str]:
    """NOUS_API_KEY only."""
    tokens: list[str] = []
    key = _first_env(_ENV_KEYS["nous"])
    if key:
        tokens.append(key)
    return tokens


def _check_nous() -> dict[str, Any]:
    """GET https://portal.nousresearch.com/api/billing/state — remaining = balanceUsd."""
    tokens = _nous_bearers()
    if not tokens:
        return {
            "provider": "nous",
            "verdict": VERDICT_UNKNOWN,
            "reason": "missing NOUS_API_KEY",
            "remaining": None,
        }
    last_http: Optional[int] = None
    body = ""
    for token in tokens:
        req = urllib.request.Request(
            "https://portal.nousresearch.com/api/billing/state",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            last_http = 200
            break
        except urllib.error.HTTPError as e:
            last_http = e.code
            if e.code in (401, 403):
                continue
            return {
                "provider": "nous",
                "verdict": VERDICT_UNKNOWN,
                "reason": f"billing API HTTP {e.code}",
                "remaining": None,
            }
        except Exception as e:
            return {
                "provider": "nous",
                "verdict": VERDICT_UNKNOWN,
                "reason": f"billing API error: {type(e).__name__}",
                "remaining": None,
            }
    else:
        return {
            "provider": "nous",
            "verdict": VERDICT_UNKNOWN,
            "reason": f"billing API HTTP {last_http}",
            "remaining": None,
        }

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {
            "provider": "nous",
            "verdict": VERDICT_UNKNOWN,
            "reason": "billing API returned non-JSON",
            "remaining": None,
        }
    if not isinstance(data, dict):
        return {
            "provider": "nous",
            "verdict": VERDICT_UNKNOWN,
            "reason": "billing API missing object body",
            "remaining": None,
        }
    try:
        remaining = float(data.get("balanceUsd") or 0)
    except (TypeError, ValueError):
        return {
            "provider": "nous",
            "verdict": VERDICT_UNKNOWN,
            "reason": "billing API missing balanceUsd",
            "remaining": None,
        }

    floor = _min_remaining()
    if remaining > floor:
        return {
            "provider": "nous",
            "verdict": VERDICT_FUNDED,
            "reason": "balanceUsd remaining above floor",
            "remaining": remaining,
        }
    return {
        "provider": "nous",
        "verdict": VERDICT_TOP_UP,
        "reason": "balanceUsd remaining at or below floor — top-up needed",
        "remaining": remaining,
    }


_LIVE_CHECKERS: dict[str, CheckerFn] = {
    "openrouter": _check_openrouter,
    "nous": _check_nous,
    "anthropic": _check_anthropic,
}


def check_one_provider(name: str) -> dict[str, Any]:
    """Return a wallet verdict for one opaque provider name (never includes secrets)."""
    canonical = normalize_provider_name(name)
    if not canonical:
        return {
            "provider": "",
            "verdict": VERDICT_UNKNOWN,
            "reason": "empty provider name",
            "remaining": None,
        }
    if canonical in NON_WALLET_PROVIDERS:
        return {
            "provider": canonical,
            "verdict": VERDICT_SKIP,
            "reason": "messaging / special-app — not a wallet",
            "remaining": None,
        }
    live = _LIVE_CHECKERS.get(canonical)
    if live is not None:
        return live()
    return _unknown_no_checker(canonical)


def check_providers(names: list[str]) -> dict[str, Any]:
    """
    Run wallet checks for every named provider.

    Returns state.provider_wallets payload:
      { checked: [...], all_funded: bool, blockers: [...] }
    """
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in names:
        canonical = normalize_provider_name(raw)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        checked.append(check_one_provider(canonical))

    blockers = [
        c
        for c in checked
        if c.get("verdict") in (VERDICT_TOP_UP, VERDICT_UNKNOWN)
    ]
    # Messaging-only (all skip) or every wallet-relevant provider funded → ok.
    wallet_relevant = [c for c in checked if c.get("verdict") != VERDICT_SKIP]
    if not wallet_relevant:
        all_funded = True
    else:
        all_funded = not blockers and all(
            c.get("verdict") == VERDICT_FUNDED for c in wallet_relevant
        )

    return {
        "checked": checked,
        "all_funded": all_funded,
        "blockers": [
            {
                "provider": b.get("provider"),
                "verdict": b.get("verdict"),
                "reason": b.get("reason"),
            }
            for b in blockers
        ],
    }


def wallets_recorded_ok(state: dict[str, Any]) -> bool:
    """True when Provider: none, or wallets were checked and all_funded."""
    providers = state.get("providers")
    if not isinstance(providers, dict) or "none" not in providers:
        return False
    if providers.get("none"):
        return True
    wallets = state.get("provider_wallets")
    if not isinstance(wallets, dict):
        return False
    return bool(wallets.get("all_funded"))


def require_provider_wallet_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    """
    begin/plan: if Provider: Yes, wallets must be checked and all funded.
    top-up / unknown → hard-stop message.
    """
    if phase not in ("begin", "plan"):
        return None
    providers = state.get("providers")
    if not isinstance(providers, dict) or "none" not in providers:
        return None  # require_provider_for_gate owns the "not recorded" error
    if providers.get("none"):
        return None

    wallets = state.get("provider_wallets")
    if not isinstance(wallets, dict):
        return (
            f"Cannot gate {phase}: provider wallets not checked. "
            "After set-provider --provider NAME …, run: "
            "ctl.py check-provider-wallet"
        )
    if wallets.get("all_funded"):
        return None

    blockers = wallets.get("blockers") or []
    parts = []
    for b in blockers:
        if not isinstance(b, dict):
            continue
        parts.append(
            f"{b.get('provider')}:{b.get('verdict')} ({b.get('reason')})"
        )
    detail = "; ".join(parts) if parts else "one or more providers not funded"
    return (
        f"Cannot gate {phase}: provider wallet hard-stop — {detail}. "
        "Top-up or fix credentials / checker, then re-run "
        "ctl.py check-provider-wallet. Do not treat as repro_failed."
    )
