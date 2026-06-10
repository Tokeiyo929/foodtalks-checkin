from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Final

from .models import BrandId, BrandMatch, BrandRecord, JsonValue, MatchReport, VisibleBrand

DATA_PATTERN: Final = re.compile(r"window\.FOODTALKS_BRANDS\s*=\s*(\[.*\]);\s*$", re.S)
SPLIT_PATTERN: Final = re.compile(r"[、,，/／;；\n\r\t|]+")
DROP_PATTERN: Final = re.compile(r"[\s\-_'\"“”‘’·.。:：()（）\[\]【】]+")


class BrandDataError(RuntimeError):
    pass


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return DROP_PATTERN.sub("", normalized)


def split_aliases(value: str) -> tuple[str, ...]:
    parts = [part.strip() for part in SPLIT_PATTERN.split(value)]
    return tuple(part for part in parts if part)


def load_brands(path: Path) -> tuple[BrandRecord, ...]:
    text = path.read_text(encoding="utf-8")
    match = DATA_PATTERN.search(text)
    if match is None:
        msg = f"Cannot find FOODTALKS_BRANDS array in {path}"
        raise BrandDataError(msg)

    raw_items: JsonValue = json.loads(match.group(1))
    match raw_items:
        case list(items):
            return tuple(parse_brand(item) for item in items)
        case _:
            msg = "FOODTALKS_BRANDS is not a JSON array"
            raise BrandDataError(msg)


def parse_brand(raw: JsonValue) -> BrandRecord:
    match raw:
        case {
            "id": int(id_value),
            "primary": str(primary),
            "secondary": str(secondary),
            "tertiary": str(tertiary),
            "company": str(company),
            "brands": str(brands),
        }:
            return BrandRecord(
                id=BrandId(id_value),
                primary=primary,
                secondary=secondary,
                tertiary=tertiary,
                company=company,
                brands=split_aliases(brands),
            )
        case _:
            msg = f"Invalid brand row: {raw!r}"
            raise BrandDataError(msg)


def build_alias_index(brands: tuple[BrandRecord, ...]) -> dict[str, tuple[BrandRecord, ...]]:
    grouped: defaultdict[str, list[BrandRecord]] = defaultdict(list)
    for brand in brands:
        aliases = (brand.company, *brand.brands)
        for alias in aliases:
            normalized = normalize_text(alias)
            if normalized:
                grouped[normalized].append(brand)
    return {alias: tuple(rows) for alias, rows in grouped.items()}


def match_visible_brands(
    photo_path: Path,
    visible: tuple[VisibleBrand, ...],
    brands: tuple[BrandRecord, ...],
    auto_threshold: float,
) -> MatchReport:
    alias_index = build_alias_index(brands)
    auto: list[BrandMatch] = []
    review: list[BrandMatch] = []
    unmatched: list[VisibleBrand] = []

    for item in visible:
        candidates = find_candidates(item.text, alias_index)
        if not candidates:
            unmatched.append(item)
            continue

        alias, rows = candidates[0]
        match_item = BrandMatch(
            photo_path=photo_path,
            detected_text=item.text,
            confidence=item.confidence,
            evidence=item.evidence,
            brand_ids=tuple(row.id for row in rows),
            matched_alias=alias,
        )
        if len(rows) == 1 and item.confidence >= auto_threshold:
            auto.append(match_item)
        else:
            review.append(match_item)

    return MatchReport(auto_write=tuple(auto), needs_review=tuple(review), unmatched=tuple(unmatched))


def find_candidates(
    detected_text: str,
    alias_index: dict[str, tuple[BrandRecord, ...]],
) -> tuple[tuple[str, tuple[BrandRecord, ...]], ...]:
    normalized = normalize_text(detected_text)
    if len(normalized) < 2:
        return ()

    matches: list[tuple[str, tuple[BrandRecord, ...]]] = []
    for alias, rows in alias_index.items():
        if alias in normalized or normalized in alias:
            matches.append((alias, rows))

    matches.sort(key=lambda item: (-len(item[0]), len(item[1])))
    return tuple(matches)
