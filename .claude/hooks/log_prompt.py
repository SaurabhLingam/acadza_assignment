"""UserPromptSubmit hook: log every user prompt verbatim.

Reads the hook payload (JSON) from stdin and appends the prompt to:
  - docs/claude-code-prompts.md   (human-readable, timestamp + session id)
  - logs/claude-code-prompts.jsonl (raw payload fields, one JSON object per line)

Design rules:
  - Never truncate or alter the prompt text.
  - Never print to stdout: for UserPromptSubmit, stdout is injected into the
    model's context. Errors go to stderr only.
  - Always exit 0 so a logging failure can never block a prompt.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root = two levels up from .claude/hooks/log_prompt.py.
# Fall back to CLAUDE_PROJECT_DIR only if the script was moved.
ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "data").is_dir() and os.environ.get("CLAUDE_PROJECT_DIR"):
    ROOT = Path(os.environ["CLAUDE_PROJECT_DIR"])

MD_PATH = ROOT / "docs" / "claude-code-prompts.md"
JSONL_PATH = ROOT / "logs" / "claude-code-prompts.jsonl"

MD_HEADER = (
    "# Claude Code prompts\n\n"
    "Every prompt typed into Claude Code in this project, verbatim. "
    "Appended automatically by `.claude/hooks/log_prompt.py` (UserPromptSubmit hook). "
    "Raw copy: `logs/claude-code-prompts.jsonl`.\n"
)


def fence_for(text: str) -> str:
    """Return a backtick fence longer than any backtick run inside text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def main() -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    payload = json.loads(raw) if raw.strip() else {}

    prompt = payload.get("prompt", "")
    session_id = payload.get("session_id", "unknown")
    event = payload.get("hook_event_name", "UserPromptSubmit")
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": ts,
        "session_id": session_id,
        "event": event,
        "cwd": payload.get("cwd"),
        "prompt": prompt,
    }
    with open(JSONL_PATH, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    new_file = not MD_PATH.exists() or MD_PATH.stat().st_size == 0
    fence = fence_for(prompt)
    source = "" if event == "UserPromptSubmit" else f" · source: {event}"
    entry = (
        f"\n---\n\n### {ts}\n\n"
        f"session: `{session_id}`{source}\n\n"
        f"{fence}text\n{prompt}\n{fence}\n"
    )
    with open(MD_PATH, "a", encoding="utf-8", newline="\n") as f:
        if new_file:
            f.write(MD_HEADER)
        f.write(entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never block the prompt
        print(f"log_prompt hook error: {exc!r}", file=sys.stderr)
    sys.exit(0)
