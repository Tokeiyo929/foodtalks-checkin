from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prediction:
    detected_text: str
    matched_alias: str
