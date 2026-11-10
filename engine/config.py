"""Models, tolerances and limits for the LLM tiers. One place to change them."""
from __future__ import annotations

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "min_interval_s": 2.5,        # client-side pacing; server rate-limit headers take precedence
        "paid": False,                # free tier: logged cost is 0
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "min_interval_s": 0.5,
        "paid": True,
    },
}

# role -> (provider, model, prompt name, prompt version, max_tokens)
ROLES = {
    "guard":        ("groq", "meta-llama/llama-prompt-guard-2-86m", "prompt_guard", 1, 16),
    "solver_1":     ("groq", "openai/gpt-oss-120b", "solver", 3, 6000),
    "solver_2":     ("openrouter", "deepseek/deepseek-v4-flash", "solver", 3, 6000),
    "extract":      ("groq", "openai/gpt-oss-20b", "extract", 1, 2000),
    "audit":        ("groq", "openai/gpt-oss-120b", "solution_audit", 3, 4000),
    "option_check": ("groq", "openai/gpt-oss-120b", "option_check", 2, 4000),
    "tiebreak":     ("openrouter", "deepseek/deepseek-v4-flash", "option_check", 2, 6000),
    "value_check":  ("groq", "openai/gpt-oss-120b", "value_check", 1, 4000),       # integerQuestion
    "value_tiebreak": ("openrouter", "deepseek/deepseek-v4-flash", "value_check", 1, 6000),
    "triage":       ("groq", "openai/gpt-oss-120b", "triage", 2, 4000),
    "reply":        ("groq", "openai/gpt-oss-20b", "reply", 3, 600),
}

# Families, so code can check that "independent" signals really are independent.
FAMILY = {"openai/gpt-oss-120b": "openai", "openai/gpt-oss-20b": "openai",
          "deepseek/deepseek-v4-flash": "deepseek", "meta-llama/llama-prompt-guard-2-86m": "meta"}

DEFAULT_SPEND_CAP_USD = 0.50
MAX_RETRIES = 4
TIMEOUT_S = 120
GUARD_THRESHOLD = 0.5            # prompt-guard score at or above this counts as an injection signal
GUARD_MAX_CHARS = 1500           # the guard model has a 512-token window

# Numeric matching (stated tolerances)
OPTION_REL_TOL = 0.01            # a value matches an option within 1 %, and only if exactly one option matches
INTEGER_REL_TOL = 0.005          # a model value matches an integer key within 0.5 % ...
INTEGER_ABS_TOL = 0.01           # ... or 0.01 absolute, whichever is larger
# A student's own integer entry must equal the key exactly: integer answers are graded as entered.

# Confidence: code computes it from how many independent sources agree (D-001)
CONF_BASE = 0.5
CONF_PER_AGREE = 0.12
CONF_PER_AGAINST = 0.20
CONF_MIN, CONF_MAX = 0.20, 0.97
CONF_DEFINITE = 0.95             # a definite code finding with nothing against it
