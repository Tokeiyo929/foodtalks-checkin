from __future__ import annotations

import csv
from pathlib import Path

from .models import BrandMatch, BrandRecord, JsonValue, MatchReport, PhotoRecord


def photo_records_json(records: tuple[PhotoRecord, ...]) -> tuple[JsonValue, ...]:
    return tuple(
        {
            "custom_id": record.custom_id,
            "path": str(record.path),
            "preview_path": str(record.preview_path),
            "size_bytes": record.size_bytes,
            "modified_ns": record.modified_ns,
            "sha256": record.sha256,
        }
        for record in records
    )


def write_match_reports(run_dir: Path, reports: tuple[MatchReport, ...]) -> None:
    auto_groups = tuple(report.auto_write for report in reports)
    review_groups = tuple(report.needs_review for report in reports)
    write_matches_csv(run_dir / "auto_write.csv", flatten(auto_groups))
    write_matches_csv(run_dir / "needs_review.csv", flatten(review_groups))
    unmatched_path = run_dir / "unmatched.csv"
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["detected_text", "confidence", "evidence"])
        for report in reports:
            for item in report.unmatched:
                writer.writerow([item.text, item.confidence, item.evidence])


def write_auto_json(run_dir: Path, reports: tuple[MatchReport, ...]) -> None:
    from .jsonio import write_json

    rows: list[JsonValue] = []
    auto_groups = tuple(report.auto_write for report in reports)
    for match_item in flatten(auto_groups):
        for brand_id in match_item.brand_ids:
            rows.append(
                {
                    "brand_id": int(brand_id),
                    "photo_path": str(match_item.photo_path),
                    "detected_text": match_item.detected_text,
                    "confidence": match_item.confidence,
                    "evidence": match_item.evidence,
                    "matched_alias": match_item.matched_alias,
                },
            )
    write_json(run_dir / "auto_write.json", rows)


def flatten(groups: tuple[tuple[BrandMatch, ...], ...]) -> tuple[BrandMatch, ...]:
    values: list[BrandMatch] = []
    for group in groups:
        values.extend(group)
    return tuple(values)


def write_matches_csv(path: Path, matches: tuple[BrandMatch, ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "photo_path",
                "detected_text",
                "confidence",
                "matched_alias",
                "brand_ids",
                "evidence",
            ],
        )
        for item in matches:
            writer.writerow(
                [
                    str(item.photo_path),
                    item.detected_text,
                    item.confidence,
                    item.matched_alias,
                    " ".join(str(int(brand_id)) for brand_id in item.brand_ids),
                    item.evidence,
                ],
            )


def brand_lookup(brands: tuple[BrandRecord, ...]) -> dict[int, BrandRecord]:
    return {int(brand.id): brand for brand in brands}
