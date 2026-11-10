"""Load versioned prompt files from prompts/ and render them.

File format: optional '---' front matter, then '# system' and '# user' sections.
Placeholders are {{name}}; rendering fails on a missing or unused variable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .loader import ROOT

PROMPT_DIR = ROOT / "prompts"
_VAR = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    file: str
    system: str
    user: str

    def render(self, **vars) -> list[dict]:
        needed = set(_VAR.findall(self.system)) | set(_VAR.findall(self.user))
        missing = needed - set(vars)
        extra = set(vars) - needed
        if missing or extra:
            raise PromptError(f"{self.file}: missing {sorted(missing)}, unused {sorted(extra)}")

        def sub(text):
            return _VAR.sub(lambda m: str(vars[m.group(1)]), text).strip()

        msgs = []
        if self.system.strip():
            msgs.append({"role": "system", "content": sub(self.system)})
        msgs.append({"role": "user", "content": sub(self.user)})
        return msgs


def load_prompt(name: str, version: int) -> Prompt:
    path = PROMPT_DIR / f"{name}_v{version}.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.index("\n---", 3)
        text = text[end + 4:]
    parts = re.split(r"^# (system|user)\s*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    if "user" not in sections:
        raise PromptError(f"{path.name}: no '# user' section")
    return Prompt(name, version, path.name, sections.get("system", ""), sections["user"])
