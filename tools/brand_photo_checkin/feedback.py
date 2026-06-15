from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import typer

from .brands import find_candidates, load_brands
from .jsonio import write_json
from .models import BrandId, BrandRecord, JsonValue

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
OFFICE_ATTR = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
TABLE_ATTR = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"

app = typer.Typer(no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class FeedbackRow:
    index: int
    correct_marker: str
    note: str
    candidate_brand: str
    photo_path: Path


@dataclass(frozen=True, slots=True)
class ApprovedFeedback:
    index: int
    brand_id: BrandId
    brand_name: str
    photo_path: Path


@app.command()
def apply(
    feedback_path: Path = typer.Argument(..., help="Filled review_feedback.ods."),
    copy_dir: Path = typer.Option(..., help="Folder for copied confirmed source photos."),
    output_json: Path = typer.Option(..., help="Approved feedback JSON for Appwrite writing."),
    brand_data: Path = typer.Option(Path("brand-checkin-data.js"), help="Path to brand-checkin-data.js."),
    checked_only: bool = typer.Option(False, help="Only approve rows explicitly marked with ✓."),
    skip_unresolved: bool = typer.Option(False, help="Skip checked rows whose brand cannot be resolved safely."),
) -> None:
    brands = load_brands(brand_data)
    approved = approve_feedback(read_feedback_ods(feedback_path), brands, checked_only, skip_unresolved)
    copy_approved_photos(approved, brands, copy_dir)
    write_json(output_json, approved_json(approved))
    typer.echo(f"Approved {len(approved)} feedback rows")


def read_feedback_ods(path: Path) -> tuple[FeedbackRow, ...]:
    with ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    table = find_review_table(root)
    rows = table_rows(table)
    headers = rows[0] if rows else ()
    parsed = tuple(parse_feedback_row(row, headers) for row in rows[1:])
    return tuple(row for row in parsed if row.correct_marker or row.note)


def find_review_table(root: ElementTree.Element) -> ElementTree.Element:
    for table in root.findall(".//table:table", NS):
        if table.attrib.get(f"{TABLE_ATTR}name") == "复核":
            return table
    msg = "Cannot find 复核 sheet in ODS"
    raise typer.BadParameter(msg)


def table_rows(table: ElementTree.Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.findall("table:table-row", NS):
        values: list[str] = []
        for cell in row.findall("table:table-cell", NS):
            repeat = int(cell.attrib.get(f"{TABLE_ATTR}number-columns-repeated", "1"))
            value = cell_text(cell)
            values.extend([value] * repeat)
        rows.append(tuple(values[:7]))
    return tuple(rows)


def cell_text(cell: ElementTree.Element) -> str:
    if cell.attrib.get(f"{OFFICE_ATTR}value-type") == "boolean":
        return "true" if cell.attrib.get(f"{OFFICE_ATTR}boolean-value") == "true" else ""
    return "".join(paragraph_text(paragraph) for paragraph in cell.findall("text:p", NS))


def paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(paragraph.itertext())


def parse_feedback_row(row: tuple[str, ...], headers: tuple[str, ...] = ()) -> FeedbackRow:
    padded = (*row, "", "", "", "", "", "", "")[:7]
    if "反馈类型" in headers:
        return parse_legacy_feedback_row(padded)
    if "备注" not in headers:
        return FeedbackRow(
            index=int(padded[0]),
            correct_marker=padded[1].strip(),
            note="",
            candidate_brand=padded[2].strip(),
            photo_path=Path(padded[4].strip()),
        )
    if padded[5].strip():
        return FeedbackRow(
            index=int(padded[0]),
            correct_marker=padded[1].strip(),
            note=padded[2].strip(),
            candidate_brand=padded[3].strip(),
            photo_path=Path(padded[5].strip()),
        )
    return FeedbackRow(
        index=int(padded[0]),
        correct_marker=padded[1].strip(),
        note="",
        candidate_brand=padded[3].strip(),
        photo_path=Path(padded[4].strip()),
    )


def parse_legacy_feedback_row(row: tuple[str, ...]) -> FeedbackRow:
    match row[1].strip():
        case "correct":
            marker = "✓"
            note = ""
        case "wrong_brand":
            marker = ""
            note = row[2].strip()
        case _:
            marker = ""
            note = ""
    return FeedbackRow(
        index=int(row[0]),
        correct_marker=marker,
        note=note,
        candidate_brand=row[4].strip(),
        photo_path=Path(row[6].strip()),
    )


def approve_feedback(
    rows: tuple[FeedbackRow, ...],
    brands: tuple[BrandRecord, ...],
    checked_only: bool = False,
    skip_unresolved: bool = False,
) -> tuple[ApprovedFeedback, ...]:
    approved: list[ApprovedFeedback] = []
    for row in rows:
        if is_checked(row.correct_marker):
            brand_name = row.candidate_brand
        elif row.note and not checked_only:
            brand_name = row.note
        else:
            continue
        try:
            brand_id = resolve_brand_id(brand_name, brands)
        except typer.BadParameter:
            if skip_unresolved:
                continue
            raise
        approved.append(
            ApprovedFeedback(
                index=row.index,
                brand_id=brand_id,
                brand_name=brand_name,
                photo_path=row.photo_path,
            ),
        )
    return tuple(approved)


def is_checked(value: str) -> bool:
    return value.strip().casefold() in {"✓", "✔", "true", "1", "yes", "y", "是", "correct"}


def resolve_brand_id(name: str, brands: tuple[BrandRecord, ...]) -> BrandId:
    alias_index = {alias: rows for alias, rows in build_alias_rows(brands).items()}
    candidates = find_candidates(name, alias_index)
    match candidates:
        case ((_, rows), *_):
            unique_rows = unique_brand_rows(rows)
            if len(unique_rows) == 1:
                return unique_rows[0].id
            ids = ", ".join(str(int(row.id)) for row in unique_rows)
            msg = f"Brand {name} is ambiguous: {ids}"
            raise typer.BadParameter(msg)
        case _:
            msg = f"Cannot match brand: {name}"
            raise typer.BadParameter(msg)


def unique_brand_rows(rows: tuple[BrandRecord, ...]) -> tuple[BrandRecord, ...]:
    unique: dict[int, BrandRecord] = {}
    for row in rows:
        unique.setdefault(int(row.id), row)
    return tuple(unique.values())


def build_alias_rows(brands: tuple[BrandRecord, ...]) -> dict[str, tuple[BrandRecord, ...]]:
    from .brands import build_alias_index

    return build_alias_index(brands)


def copy_approved_photos(
    rows: tuple[ApprovedFeedback, ...],
    brands: tuple[BrandRecord, ...],
    copy_dir: Path,
) -> None:
    brand_map = {int(brand.id): brand for brand in brands}
    for row in rows:
        brand = brand_map[int(row.brand_id)]
        target_dir = copy_dir / brand_folder_name(brand)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row.photo_path, unique_destination(target_dir / row.photo_path.name))


def brand_folder_name(brand: BrandRecord) -> str:
    label = brand.brands[0] if brand.brands else brand.company
    return f"brand-{int(brand.id):04d}-{safe_path_part(label)}"


def safe_path_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return cleaned or "unknown"


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    msg = f"Cannot find available destination for {path}"
    raise typer.BadParameter(msg)


def approved_json(rows: tuple[ApprovedFeedback, ...]) -> JsonValue:
    return [
        {
            "index": row.index,
            "brand_id": int(row.brand_id),
            "brand_name": row.brand_name,
            "photo_path": str(row.photo_path),
        }
        for row in rows
    ]


if __name__ == "__main__":
    app()
