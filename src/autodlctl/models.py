from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StepResult:
    op: str
    ok: bool
    detail: dict[str, Any]
