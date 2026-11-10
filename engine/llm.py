"""One client for Groq and OpenRouter (both OpenAI-compatible chat completions).

- per-provider pacing plus rate-limit headers (retry-after, x-ratelimit-*)
- retries with exponential backoff and jitter on 429 / 5xx / timeouts
- response cache in .cache/llm/ keyed by provider, model, prompt file+version, messages, params
- one JSON line per call in logs/llm-calls.jsonl (CLAUDE.md section 4, plus the model and
  upstream provider that actually answered and the actual cost)
- a hard spend cap: a paid call whose worst-case cost would cross the cap is never sent;
  BudgetExceeded is raised so the run can stop cleanly

The HTTP transport is injectable so tests run with no network.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .loader import ROOT
from .prompts import Prompt

CACHE_DIR = ROOT / ".cache" / "llm"
CALL_LOG = ROOT / "logs" / "llm-calls.jsonl"
USER_AGENT = "report-fix-engine/0.1"


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def load_env() -> dict:
    env = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def urllib_transport(method: str, url: str, headers: dict, body: dict | None, timeout: float):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read().decode("utf-8", "replace")


@dataclass
class Result:
    content: str
    data: dict | None
    model_requested: str
    model_answered: str
    provider: str
    upstream_provider: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_hit: bool
    retries: int
    latency_ms: int


@dataclass
class Spend:
    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, cost: float):
        self.spent_usd += cost
        self.calls += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + cost


def _duration_s(v: str | None) -> float | None:
    """Parse '2.5', '7.66s', '500ms', '1m3.2s'."""
    if not v:
        return None
    v = v.strip()
    try:
        return float(v)
    except ValueError:
        pass
    total, matched = 0.0, False
    for num, unit in re.findall(r"([\d.]+)\s*(ms|h|m|s)", v):
        matched = True
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total if matched else None


def parse_json(text: str) -> dict | None:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(t[start:i + 1])
                        return v if isinstance(v, dict) else None
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    return None


class Client:
    def __init__(self, run_id: str, cap_usd: float = config.DEFAULT_SPEND_CAP_USD, transport=None,
                 env: dict | None = None, use_cache: bool = True, log_path=CALL_LOG, cache_dir=CACHE_DIR,
                 sleep=time.sleep, offline: bool = False):
        self.run_id = run_id
        self.spend = Spend(cap_usd)
        self.transport = transport or urllib_transport
        self.env = env if env is not None else load_env()
        self.use_cache = use_cache
        self.log_path, self.cache_dir = log_path, cache_dir
        self.sleep = sleep
        self.offline = offline            # True: never touch the network (cache hits only)
        self._last_call: dict[str, float] = {}
        self._wait_until: dict[str, float] = {}
        self._prices: dict[str, tuple[float, float]] | None = None
        self._dropped_params: dict[str, set] = {}
        self.calls_by_stage: dict[str, int] = {}
        self.tokens_in_total = 0
        self.tokens_out_total = 0

    # ---------------------------------------------------------------- pricing
    def prices(self) -> dict[str, tuple[float, float]]:
        """OpenRouter list prices (USD per token), read once per run from the model-list endpoint."""
        if self._prices is None:
            if self.offline:
                self._prices = {}
            else:
                st, _, body = self.transport("GET", config.PROVIDERS["openrouter"]["base_url"] + "/models",
                                             self._headers("openrouter"), None, config.TIMEOUT_S)
                if st != 200:
                    raise LLMError(f"OpenRouter model list: HTTP {st}")
                self._prices = {}
                for m in json.loads(body).get("data", []):
                    p = m.get("pricing") or {}
                    try:
                        self._prices[m["id"]] = (float(p.get("prompt", 0)), float(p.get("completion", 0)))
                    except (TypeError, ValueError):
                        continue
        return self._prices

    def _price(self, provider: str, model: str) -> tuple[float, float]:
        if not config.PROVIDERS[provider]["paid"]:
            return 0.0, 0.0
        p = self.prices().get(model)
        if p is None:
            raise BudgetExceeded(f"no list price for paid model {model}; refusing to call it")
        return p

    # ---------------------------------------------------------------- plumbing
    def _headers(self, provider: str) -> dict:
        key = self.env.get(config.PROVIDERS[provider]["key_env"], "")
        h = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def _pace(self, provider: str):
        now = time.monotonic()
        wait = max(self._wait_until.get(provider, 0) - now,
                   self._last_call.get(provider, -1e9) + config.PROVIDERS[provider]["min_interval_s"] - now)
        if wait > 0:
            self.sleep(wait)
        self._last_call[provider] = time.monotonic()

    def _note_limits(self, provider: str, headers: dict):
        waits = []
        for rem, reset in (("x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
                           ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens")):
            try:
                if rem in headers and float(headers[rem]) <= 0:
                    waits.append(_duration_s(headers.get(reset)) or 1.0)
            except ValueError:
                pass
        if waits:
            self._wait_until[provider] = time.monotonic() + max(waits)

    def _log(self, rec: dict):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------------------------------------------------------------- the call
    def call(self, role: str, prompt: Prompt | None, messages: list[dict], *, stage: str, tier: int,
             subject: str = "", json_mode: bool = True, temperature: float | None = 0.0) -> Result:
        provider, model, _, _, max_tokens = config.ROLES[role]
        params = {"max_tokens": max_tokens}
        if temperature is not None:
            params["temperature"] = temperature
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        prompt_file = prompt.file if prompt else ""
        prompt_version = prompt.version if prompt else 0
        key_material = json.dumps([provider, model, prompt_file, prompt_version, messages, params],
                                  ensure_ascii=False, sort_keys=True)
        input_hash = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]
        self.calls_by_stage[stage] = self.calls_by_stage.get(stage, 0) + 1
        base = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": self.run_id,
                "stage": stage, "tier": tier, "role": role, "subject": subject, "provider": provider,
                "model": model, "prompt_file": prompt_file, "prompt_version": prompt_version,
                "input_hash": input_hash}

        cache_file = self.cache_dir / f"{input_hash}.json"
        if self.use_cache and cache_file.exists():
            c = json.loads(cache_file.read_text(encoding="utf-8"))
            self._log({**base, "model_answered": c["model_answered"], "upstream_provider": c["upstream_provider"],
                       "tokens_in": c["tokens_in"], "tokens_out": c["tokens_out"], "latency_ms": 0,
                       "cache_hit": True, "retries": 0, "cost_usd": 0.0, "cost_source": "cache", "status": "ok"})
            return Result(c["content"], parse_json(c["content"]) if json_mode else None, model,
                          c["model_answered"], provider, c["upstream_provider"], c["tokens_in"], c["tokens_out"],
                          0.0, True, 0, 0)
        if self.offline:
            raise LLMError(f"offline mode and no cache entry for {role}/{subject}")

        pin, pout = self._price(provider, model)
        est_in = sum(len(m["content"]) for m in messages) / 3 + 50   # conservative: ~3 chars per token
        worst = est_in * pin + max_tokens * pout
        if self.spend.spent_usd + worst > self.spend.cap_usd:
            self._log({**base, "status": "budget_stop", "cache_hit": False, "retries": 0, "cost_usd": 0.0,
                       "worst_case_usd": round(worst, 6), "spent_usd": round(self.spend.spent_usd, 6),
                       "cap_usd": self.spend.cap_usd})
            raise BudgetExceeded(f"{role}: worst case ${worst:.4f} would exceed cap "
                                 f"${self.spend.cap_usd:.2f} (spent ${self.spend.spent_usd:.4f})")

        url = config.PROVIDERS[provider]["base_url"] + "/chat/completions"
        body = {"model": model, "messages": list(messages), **params}
        if provider == "openrouter":
            body["usage"] = {"include": True}
        for p in self._dropped_params.get(model, ()):
            body.pop(p, None)

        retries, t0, json_repair_used = 0, time.monotonic(), False
        while True:
            if retries and self.spend.spent_usd + worst > self.spend.cap_usd:
                self._log({**base, "status": "budget_stop", "cache_hit": False, "retries": retries,
                           "cost_usd": 0.0, "worst_case_usd": round(worst, 6),
                           "spent_usd": round(self.spend.spent_usd, 6), "cap_usd": self.spend.cap_usd})
                raise BudgetExceeded(f"{role}: retry would exceed cap ${self.spend.cap_usd:.2f}")
            self._pace(provider)
            try:
                st, hdrs, text = self.transport("POST", url, self._headers(provider), body, config.TIMEOUT_S)
            except Exception as e:  # network error / timeout
                st, hdrs, text = None, {}, repr(e)
            self._note_limits(provider, hdrs)
            if st == 200:
                resp = json.loads(text)
                content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                data = parse_json(content) if json_mode else None
                if json_mode and data is None and not json_repair_used and retries < config.MAX_RETRIES:
                    json_repair_used, retries = True, retries + 1
                    body["messages"] = list(messages) + [
                        {"role": "assistant", "content": content[:2000]},
                        {"role": "user", "content": "That was not a valid JSON object. Reply with the JSON object only."}]
                    self._account(provider, model, resp, pin, pout)
                    continue
                break
            bad_param = None
            if st == 400:
                for p in ("response_format", "temperature"):
                    if p in body and p in text:
                        bad_param = p
            if bad_param:
                self._dropped_params.setdefault(model, set()).add(bad_param)
                body.pop(bad_param)
                retries += 1
                continue
            retryable = st is None or st == 429 or st >= 500
            if not retryable or retries >= config.MAX_RETRIES:
                self._log({**base, "status": "error", "http_status": st, "error": text[:300], "cache_hit": False,
                           "retries": retries, "latency_ms": int((time.monotonic() - t0) * 1000), "cost_usd": 0.0})
                raise LLMError(f"{role}: HTTP {st}: {text[:200]}")
            retries += 1
            wait = _duration_s(hdrs.get("retry-after")) or min(60.0, 2 ** retries) * (0.5 + random.random())
            self.sleep(wait)

        cost, cost_source = self._account(provider, model, resp, pin, pout)
        usage = resp.get("usage") or {}
        self.tokens_in_total += int(usage.get("prompt_tokens") or 0)
        self.tokens_out_total += int(usage.get("completion_tokens") or 0)
        res = Result(
            content=content, data=data, model_requested=model, model_answered=resp.get("model", ""),
            provider=provider, upstream_provider=resp.get("provider", provider),
            tokens_in=int(usage.get("prompt_tokens") or 0), tokens_out=int(usage.get("completion_tokens") or 0),
            cost_usd=cost, cache_hit=False, retries=retries, latency_ms=int((time.monotonic() - t0) * 1000))
        self._log({**base, "model_answered": res.model_answered, "upstream_provider": res.upstream_provider,
                   "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "latency_ms": res.latency_ms,
                   "cache_hit": False, "retries": retries, "cost_usd": round(cost, 8), "cost_source": cost_source,
                   "status": "ok" if (data is not None or not json_mode) else "bad_json",
                   "dropped_params": sorted(self._dropped_params.get(model, ()))})
        if self.use_cache and (data is not None or not json_mode):
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({
                "content": content, "model_answered": res.model_answered, "upstream_provider": res.upstream_provider,
                "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}, ensure_ascii=False), encoding="utf-8")
        return res

    def _account(self, provider, model, resp, pin, pout) -> tuple[float, str]:
        usage = resp.get("usage") or {}
        if not config.PROVIDERS[provider]["paid"]:
            cost, src = 0.0, "free_tier"
        elif isinstance(usage.get("cost"), (int, float)):
            cost, src = float(usage["cost"]), "provider_usage"
        else:
            cost = int(usage.get("prompt_tokens") or 0) * pin + int(usage.get("completion_tokens") or 0) * pout
            src = "list_price_estimate"
        self.spend.add(model, cost)
        return cost, src
