from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
import shutil
from time import sleep
from typing import Annotated

import typer

from .appwrite import AppwriteClient
from .brands import load_brands, match_visible_brands
from .config import read_appwrite_config
from .jsonio import read_jsonl, write_json, write_jsonl
from .local_env import load_local_env
from .models import AutoWriteRow, BrandId, BrandRecord, JsonValue, MatchReport
from .openai_batch import (
    OpenAIClient,
    OpenAIRequestError,
    build_batch_request,
    parse_visible_brands,
    response_body_from_batch_request,
)
from .photos import scan_photos
from .progress import write_progress
from .reports import photo_records_json, write_auto_json, write_match_reports

app = typer.Typer(no_args_is_help=True)
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_RUN_DIR = Path("photo-runs/latest")
DEFAULT_BRAND_DATA = Path("brand-checkin-data.js")
DEFAULT_APPWRITE_CONFIG = Path("appwrite-config.js")


@app.command()
def prepare(
    photos: Annotated[Path, typer.Argument(help="Photo file or folder to scan.")],
    run_dir: Annotated[Path, typer.Option(help="Output run directory.")] = DEFAULT_RUN_DIR,
    limit: Annotated[int | None, typer.Option(help="Optional max photo count.")] = None,
    offset: Annotated[int, typer.Option(help="Number of sorted photos to skip before preparing.")] = 0,
    model: Annotated[str, typer.Option(help="OpenAI vision model for batch requests.")] = DEFAULT_MODEL,
    image_detail: Annotated[str, typer.Option(help="Responses API image detail.")] = "low",
) -> None:
    records = scan_photos(photos, run_dir, limit, offset)
    requests = tuple(build_batch_request(record, model, image_detail) for record in records)
    write_jsonl(run_dir / "photos.jsonl", photo_records_json(records))
    write_jsonl(run_dir / "batch_requests.jsonl", requests)
    typer.echo(f"Prepared {len(records)} photos in {run_dir}")


@app.command()
def submit_batch(
    run_dir: Annotated[Path, typer.Argument(help="Run directory from prepare.")],
) -> None:
    client = OpenAIClient.from_env()
    file_id = client.upload_batch_file(run_dir / "batch_requests.jsonl")
    batch_id = client.create_batch(file_id)
    write_json(run_dir / "openai_batch.json", {"file_id": file_id, "batch_id": batch_id})
    typer.echo(f"Created OpenAI batch {batch_id}")


@app.command()
def fetch_batch(
    batch_id: Annotated[str, typer.Argument(help="OpenAI batch id.")],
    run_dir: Annotated[Path, typer.Argument(help="Run directory to store output.")],
) -> None:
    client = OpenAIClient.from_env()
    metadata = client.get_batch(batch_id)
    write_json(run_dir / "openai_batch_status.json", metadata)
    match metadata:
        case {"output_file_id": str(output_file_id)}:
            client.download_file(output_file_id, run_dir / "batch_output.jsonl")
            typer.echo(f"Downloaded batch output file {output_file_id}")
        case {"status": str(status)}:
            typer.echo(f"Batch status: {status}")
        case _:
            typer.echo("Batch metadata saved; output file is not available yet.")


@app.command()
def run_sync(
    run_dir: Annotated[Path, typer.Argument(help="Run directory from prepare.")],
    retries: Annotated[int, typer.Option(help="Retries per photo after transient request failures.")] = 3,
    retry_delay_seconds: Annotated[float, typer.Option(help="Delay between per-photo retries.")] = 5.0,
) -> None:
    client = OpenAIClient.from_env()
    rows = read_jsonl(run_dir / "batch_requests.jsonl")
    output_path = run_dir / "batch_output.jsonl"
    completed_ids = read_completed_output_ids(output_path)
    written = 0
    skipped = 0
    total = len(rows)
    write_progress(
        run_dir,
        phase="run-sync",
        status="running",
        total=total,
        completed=len(completed_ids),
        skipped=skipped,
        failed=0,
        current_id="",
        message="Starting sync OpenAI photo recognition.",
    )
    for row in rows:
        custom_id = custom_id_from_request(row)
        if custom_id in completed_ids:
            skipped += 1
            typer.echo(f"Skipped {custom_id}")
            write_progress(
                run_dir,
                phase="run-sync",
                status="running",
                total=total,
                completed=len(completed_ids) + written,
                skipped=skipped,
                failed=0,
                current_id=custom_id,
                message=f"Skipped already completed {custom_id}.",
            )
            continue
        body = response_body_from_batch_request(row)
        write_progress(
            run_dir,
            phase="run-sync",
            status="running",
            total=total,
            completed=len(completed_ids) + written,
            skipped=skipped,
            failed=0,
            current_id=custom_id,
            message=f"Processing {custom_id}.",
        )
        try:
            response = create_response_with_retries(client, body, custom_id, retries, retry_delay_seconds)
        except (OpenAIRequestError, OSError) as error:
            write_progress(
                run_dir,
                phase="run-sync",
                status="failed",
                total=total,
                completed=len(completed_ids) + written,
                skipped=skipped,
                failed=1,
                current_id=custom_id,
                message=f"Failed {custom_id}: {error}",
            )
            raise
        append_jsonl_row(output_path, successful_response_row(custom_id, response))
        written += 1
        typer.echo(f"Processed {custom_id}")
        write_progress(
            run_dir,
            phase="run-sync",
            status="running",
            total=total,
            completed=len(completed_ids) + written,
            skipped=skipped,
            failed=0,
            current_id=custom_id,
            message=f"Processed {custom_id}.",
        )
    response_total = len(completed_ids) + written
    write_progress(
        run_dir,
        phase="run-sync",
        status="completed",
        total=total,
        completed=response_total,
        skipped=skipped,
        failed=0,
        current_id="",
        message=f"Wrote {written} new response rows; {response_total} total rows.",
    )
    typer.echo(f"Wrote {written} new response rows; {response_total} total rows in {output_path}")


@app.command()
def ingest(
    run_dir: Annotated[Path, typer.Argument(help="Run directory from prepare/fetch-batch.")],
    brand_data: Annotated[Path, typer.Option(help="Path to brand-checkin-data.js.")] = DEFAULT_BRAND_DATA,
    threshold: Annotated[float, typer.Option(help="Minimum confidence for unambiguous auto-write.")] = 0.82,
) -> None:
    brands = load_brands(brand_data)
    photo_paths = load_photo_path_map(run_dir / "photos.jsonl")
    rows = read_jsonl(run_dir / "batch_output.jsonl")
    reports: list[MatchReport] = []
    for row in rows:
        custom_id, body = parse_batch_row(row)
        visible = parse_visible_brands(body)
        photo_path = photo_paths.get(custom_id, Path(custom_id))
        reports.append(match_visible_brands(photo_path, visible, brands, threshold))
    report_tuple = tuple(reports)
    write_match_reports(run_dir, report_tuple)
    write_auto_json(run_dir, report_tuple)
    typer.echo(f"Wrote reports for {len(report_tuple)} photos in {run_dir}")


@app.command()
def write_appwrite(
    run_dir: Annotated[Path, typer.Argument(help="Run directory containing auto_write.json.")],
    config_path: Annotated[Path, typer.Option(help="Path to appwrite-config.js.")] = DEFAULT_APPWRITE_CONFIG,
    execute: Annotated[bool, typer.Option(help="Actually write Appwrite rows.")] = False,
) -> None:
    load_local_env()
    user_id = os.environ.get("APPWRITE_USER_ID", "").strip()
    if not user_id:
        raise typer.BadParameter("APPWRITE_USER_ID is required")

    rows = read_auto_rows(run_dir / "auto_write.json")
    checked_at = datetime.now(UTC).isoformat()
    write_json(run_dir / "rollback.json", rollback_rows(rows))
    if not execute:
        typer.echo(f"Dry run: {len(rows)} brand ids would be written for user {user_id}")
        return

    client = AppwriteClient.from_env(read_appwrite_config(config_path))
    log_rows: list[JsonValue] = []
    for brand_id in rows:
        result = client.upsert_checkin(user_id, brand_id, checked_at)
        log_rows.append({"brand_id": int(brand_id), "result": result})
    write_jsonl(run_dir / "appwrite_write_log.jsonl", tuple(log_rows))
    typer.echo(f"Wrote {len(rows)} check-ins to Appwrite")


@app.command()
def write_approved_appwrite(
    approved_json: Annotated[Path, typer.Argument(help="Approved feedback JSON from review ODS.")],
    config_path: Annotated[Path, typer.Option(help="Path to appwrite-config.js.")] = DEFAULT_APPWRITE_CONFIG,
    execute: Annotated[bool, typer.Option(help="Actually write Appwrite rows.")] = False,
) -> None:
    load_local_env()
    user_id = os.environ.get("APPWRITE_USER_ID", "").strip()
    if not user_id:
        raise typer.BadParameter("APPWRITE_USER_ID is required")

    rows = read_approved_rows(approved_json)
    checked_at = datetime.now(UTC).isoformat()
    if not execute:
        typer.echo(f"Dry run: {len(rows)} approved brand ids would be written for user {user_id}")
        return

    client = AppwriteClient.from_env(read_appwrite_config(config_path))
    log_rows: list[JsonValue] = []
    for brand_id in rows:
        result = client.upsert_checkin(user_id, brand_id, checked_at)
        verification = client.find_checkin(user_id, brand_id)
        log_rows.append({"brand_id": int(brand_id), "result": result, "verification": verification})
    write_jsonl(approved_json.parent / "appwrite_feedback_write_log.jsonl", tuple(log_rows))
    typer.echo(f"Wrote {len(rows)} approved check-ins to Appwrite")


@app.command()
def copy_matches(
    run_dir: Annotated[Path, typer.Argument(help="Run directory containing auto_write.json.")],
    output_dir: Annotated[Path, typer.Option(help="Folder for copied matched source photos.")],
    brand_data: Annotated[Path, typer.Option(help="Path to brand-checkin-data.js.")] = DEFAULT_BRAND_DATA,
) -> None:
    rows = read_auto_match_rows(run_dir / "auto_write.json")
    brands = {int(brand.id): brand for brand in load_brands(brand_data)}
    copied = 0
    for row in rows:
        brand = brands.get(int(row.brand_id))
        if brand is None or not row.photo_path.exists():
            continue
        folder = output_dir / brand_folder_name(brand)
        folder.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(folder / row.photo_path.name)
        shutil.copy2(row.photo_path, destination)
        copied += 1
    typer.echo(f"Copied {copied} matched source photos to {output_dir}")


@app.command()
def cleanup_run(
    run_dir: Annotated[Path, typer.Argument(help="Run directory to clean.")],
    keep_reports: Annotated[bool, typer.Option(help="Keep CSV/JSON match reports.")] = True,
) -> None:
    targets = [
        run_dir / "previews",
        run_dir / "batch_requests.jsonl",
        run_dir / "batch_output.jsonl",
        run_dir / "photos.jsonl",
        run_dir / "openai_batch.json",
        run_dir / "openai_batch_status.json",
        run_dir / "rollback.json",
        run_dir / "appwrite_write_log.jsonl",
    ]
    if not keep_reports:
        targets.extend(
            [
                run_dir / "auto_write.csv",
                run_dir / "auto_write.json",
                run_dir / "needs_review.csv",
                run_dir / "unmatched.csv",
            ],
        )
    for target in targets:
        delete_target(target)
    typer.echo(f"Cleaned sensitive artifacts in {run_dir}")


def delete_target(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        return
    if path.exists():
        path.unlink()


def load_photo_path_map(path: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for row in read_jsonl(path):
        match row:
            case {"custom_id": str(custom_id), "path": str(photo_path)}:
                mapping[custom_id] = Path(photo_path)
            case _:
                continue
    return mapping


def custom_id_from_request(row: JsonValue) -> str:
    match row:
        case {"custom_id": str(custom_id)}:
            return custom_id
        case _:
            return "unknown"


def read_completed_output_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    for row in read_jsonl(path):
        match row:
            case {"custom_id": str(custom_id)}:
                completed.add(custom_id)
            case _:
                continue
    return completed


def create_response_with_retries(
    client: OpenAIClient,
    body: JsonValue,
    custom_id: str,
    retries: int,
    retry_delay_seconds: float,
) -> JsonValue:
    for attempt in range(retries + 1):
        try:
            return client.create_response(body)
        except (OpenAIRequestError, OSError) as error:
            if attempt >= retries:
                raise
            typer.echo(f"Retrying {custom_id} after request error ({attempt + 1}/{retries}): {error}")
            if retry_delay_seconds > 0:
                sleep(retry_delay_seconds)
    msg = f"Failed to process {custom_id}"
    raise OpenAIRequestError(msg)


def successful_response_row(custom_id: str, response: JsonValue) -> JsonValue:
    return {
        "custom_id": custom_id,
        "response": {"status_code": 200, "body": response},
    }


def append_jsonl_row(path: Path, row: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        _ = file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        _ = file.write("\n")


def parse_batch_row(row: JsonValue) -> tuple[str, JsonValue]:
    match row:
        case {
            "custom_id": str(custom_id),
            "response": {"body": dict(body)},
        }:
            return custom_id, body
        case {"custom_id": str(custom_id), "error": dict(error)}:
            return custom_id, {"output_text": json.dumps({"visible_brand_names": [], "notes": str(error)})}
        case _:
            return "unknown", {"output_text": '{"visible_brand_names":[],"notes":"invalid batch row"}'}


def read_auto_rows(path: Path) -> tuple[BrandId, ...]:
    return tuple(dict.fromkeys(row.brand_id for row in read_auto_match_rows(path)))


def read_approved_rows(path: Path) -> tuple[BrandId, ...]:
    rows: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    parsed: list[BrandId] = []
    match rows:
        case list(items):
            for item in items:
                match item:
                    case {"brand_id": int(brand_id)}:
                        parsed.append(BrandId(brand_id))
                    case _:
                        continue
        case _:
            raise typer.BadParameter("approved_feedback.json must be a list")
    return tuple(dict.fromkeys(parsed))


def read_auto_match_rows(path: Path) -> tuple[AutoWriteRow, ...]:
    rows: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    parsed: list[AutoWriteRow] = []
    match rows:
        case list(items):
            for item in items:
                match item:
                    case {
                        "brand_id": int(brand_id),
                        "photo_path": str(photo_path),
                        "detected_text": str(detected_text),
                        "confidence": int(confidence),
                        "matched_alias": str(matched_alias),
                    }:
                        parsed.append(
                            AutoWriteRow(
                                brand_id=BrandId(brand_id),
                                photo_path=Path(photo_path),
                                detected_text=detected_text,
                                confidence=float(confidence),
                                matched_alias=matched_alias,
                            ),
                        )
                    case {
                        "brand_id": int(brand_id),
                        "photo_path": str(photo_path),
                        "detected_text": str(detected_text),
                        "confidence": float(confidence),
                        "matched_alias": str(matched_alias),
                    }:
                        parsed.append(
                            AutoWriteRow(
                                brand_id=BrandId(brand_id),
                                photo_path=Path(photo_path),
                                detected_text=detected_text,
                                confidence=confidence,
                                matched_alias=matched_alias,
                            ),
                        )
                    case _:
                        continue
        case _:
            raise typer.BadParameter("auto_write.json must be a list")
    return tuple(parsed)


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


def rollback_rows(rows: tuple[BrandId, ...]) -> JsonValue:
    return [{"brand_id": int(brand_id), "action": "delete_if_created_by_this_run"} for brand_id in rows]


if __name__ == "__main__":
    app()
