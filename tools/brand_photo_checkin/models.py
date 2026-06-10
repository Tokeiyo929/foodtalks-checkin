from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NewType, TypeAlias

BrandId = NewType("BrandId", int)

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class BrandRecord:
    id: BrandId
    primary: str
    secondary: str
    tertiary: str
    company: str
    brands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PhotoRecord:
    custom_id: str
    path: Path
    preview_path: Path
    size_bytes: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VisibleBrand:
    text: str
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class BrandMatch:
    photo_path: Path
    detected_text: str
    confidence: float
    evidence: str
    brand_ids: tuple[BrandId, ...]
    matched_alias: str


@dataclass(frozen=True, slots=True)
class AutoWriteRow:
    brand_id: BrandId
    photo_path: Path
    detected_text: str
    confidence: float
    matched_alias: str


@dataclass(frozen=True, slots=True)
class MatchReport:
    auto_write: tuple[BrandMatch, ...]
    needs_review: tuple[BrandMatch, ...]
    unmatched: tuple[VisibleBrand, ...]


@dataclass(frozen=True, slots=True)
class AppwriteConfig:
    endpoint: str
    project_id: str
    database_id: str
    table_id: str
