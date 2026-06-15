from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from .appwrite import AppwriteClient
from .config import read_appwrite_config
from .jsonio import write_json
from .local_env import load_local_env
from .models import BrandId, JsonValue

DEFAULT_APPWRITE_CONFIG: Final = Path("appwrite-config.js")

app = typer.Typer(no_args_is_help=True)


class UncheckedGateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GateSummary:
    checked_brand_ids: int
    auto_write_json_before: int
    auto_write_json_after: int
    auto_write_csv_before: int
    auto_write_csv_after: int
    needs_review_csv_before: int
    needs_review_csv_after: int

    def json_value(self) -> JsonValue:
        return {
            "checked_brand_ids": self.checked_brand_ids,
            "auto_write_json_before": self.auto_write_json_before,
            "auto_write_json_after": self.auto_write_json_after,
            "auto_write_csv_before": self.auto_write_csv_before,
            "auto_write_csv_after": self.auto_write_csv_after,
            "needs_review_csv_before": self.needs_review_csv_before,
            "needs_review_csv_after": self.needs_review_csv_after,
        }


@app.command()
def filter_run(
    run_dir: Path = typer.Argument(..., help="Run directory containing ingest reports."),
    config_path: Path = typer.Option(DEFAULT_APPWRITE_CONFIG, help="Path to appwrite-config.js."),
) -> None:
    load_local_env()
    user_id = os.environ.get("APPWRITE_USER_ID", "").strip()
    if not user_id:
        raise typer.BadParameter("APPWRITE_USER_ID is required")

    client = AppwriteClient.from_env(read_appwrite_config(config_path))
    checked_ids = client.list_checked_brand_ids(user_id)
    summary = filter_run_files(run_dir, checked_ids)
    write_json(run_dir / "unchecked_gate_summary.json", summary.json_value())
    typer.echo(
        "Filtered review candidates against "
        f"{summary.checked_brand_ids} Appwrite checked brand IDs: "
        f"auto_write.json {summary.auto_write_json_before}->{summary.auto_write_json_after}, "
        f"auto_write.csv {summary.auto_write_csv_before}->{summary.auto_write_csv_after}, "
        f"needs_review.csv {summary.needs_review_csv_before}->{summary.needs_review_csv_after}",
    )


def filter_run_files(run_dir: Path, checked_ids: tuple[BrandId, ...]) -> GateSummary:
    checked = set(checked_ids)
    auto_json_before, auto_json_after = filter_auto_write_json(run_dir / "auto_write.json", checked)
    auto_csv_before, auto_csv_after = filter_candidate_csv(run_dir / "auto_write.csv", checked)
    review_csv_before, review_csv_after = filter_candidate_csv(run_dir / "needs_review.csv", checked)
    return GateSummary(
        checked_brand_ids=len(checked),
        auto_write_json_before=auto_json_before,
        auto_write_json_after=auto_json_after,
        auto_write_csv_before=auto_csv_before,
        auto_write_csv_after=auto_csv_after,
        needs_review_csv_before=review_csv_before,
        needs_review_csv_after=review_csv_after,
    )


def filter_auto_write_json(path: Path, checked_ids: set[BrandId]) -> tuple[int, int]:
    rows = read_auto_write_rows(path)
    kept = tuple(row for row in rows if row_brand_id(row) not in checked_ids)
    write_json(path, list(kept))
    return len(rows), len(kept)


def read_auto_write_rows(path: Path) -> tuple[dict[str, JsonValue], ...]:
    raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    match raw:
        case list(items):
            rows: list[dict[str, JsonValue]] = []
            for item in items:
                match item:
                    case dict(row):
                        rows.append(row)
                    case _:
                        continue
            return tuple(rows)
        case _:
            msg = f"{path} must contain a JSON list"
            raise UncheckedGateError(msg)


def row_brand_id(row: dict[str, JsonValue]) -> BrandId | None:
    match row:
        case {"brand_id": int(brand_id)}:
            return BrandId(brand_id)
        case _:
            return None


def filter_candidate_csv(path: Path, checked_ids: set[BrandId]) -> tuple[int, int]:
    rows, fieldnames = read_candidate_csv(path)
    kept = tuple(row for row in rows if has_unchecked_brand_id(row, checked_ids))
    write_candidate_csv(path, fieldnames, kept)
    return len(rows), len(kept)


def read_candidate_csv(path: Path) -> tuple[tuple[dict[str, str], ...], tuple[str, ...]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        return tuple(dict(row) for row in reader), fieldnames


def has_unchecked_brand_id(row: dict[str, str], checked_ids: set[BrandId]) -> bool:
    ids = parse_brand_ids(row.get("brand_ids", ""))
    unchecked = tuple(brand_id for brand_id in ids if brand_id not in checked_ids)
    if not unchecked:
        return False
    row["brand_ids"] = " ".join(str(int(brand_id)) for brand_id in unchecked)
    return True


def parse_brand_ids(value: str) -> tuple[BrandId, ...]:
    ids: list[BrandId] = []
    for part in value.replace(",", " ").split():
        try:
            ids.append(BrandId(int(part)))
        except ValueError as error:
            msg = f"Invalid brand_id value {part!r}"
            raise UncheckedGateError(msg) from error
    return tuple(ids)


def write_candidate_csv(path: Path, fieldnames: tuple[str, ...], rows: tuple[dict[str, str], ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    app()
