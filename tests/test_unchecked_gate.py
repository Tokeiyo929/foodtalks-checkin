from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from tools.brand_photo_checkin.appwrite import (
    AppwriteClient,
    checked_brand_ids_from_response,
    query_offset,
)
from tools.brand_photo_checkin.models import AppwriteConfig, BrandId, JsonValue
from tools.brand_photo_checkin.unchecked_gate import filter_run_files


class PagingTransport:
    def __init__(self, pages: tuple[JsonValue, ...]) -> None:
        self.pages = list(pages)
        self.calls: list[str] = []

    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: JsonValue | None,
    ) -> JsonValue:
        _ = (headers, body)
        self.calls.append(f"{method} {url}")
        if not self.pages:
            return {"rows": []}
        return self.pages.pop(0)


def appwrite_client(transport: PagingTransport) -> AppwriteClient:
    return AppwriteClient(
        config=AppwriteConfig(
            endpoint="https://example.appwrite.io/v1",
            project_id="project",
            database_id="db",
            table_id="table",
        ),
        api_key="key",
        transport=transport,
    )


def test_appwrite_list_checked_brand_ids_when_rows_are_paginated() -> None:
    transport = PagingTransport(({"rows": [{"brand_id": 7}]}, {"rows": [{"brand_id": 8}]}, {"rows": []}))
    client = appwrite_client(transport)

    rows = client.list_checked_brand_ids("user-1", page_size=1)

    assert tuple(int(row) for row in rows) == (7, 8)
    assert len(transport.calls) == 3
    assert query_offset(1) in decoded_queries(transport.calls[1])


def test_checked_brand_ids_from_response_when_brand_id_is_nested_in_data() -> None:
    response: JsonValue = {"rows": [{"data": {"brand_id": 9}}, {"brand_id": 10}]}

    rows = checked_brand_ids_from_response(response)

    assert tuple(int(row) for row in rows) == (9, 10)


def test_filter_run_files_removes_only_appwrite_checked_candidates(tmp_path: Path) -> None:
    run_dir = tmp_path
    (run_dir / "auto_write.json").write_text(
        json.dumps(
            [
                {"brand_id": 7, "photo_path": "a.jpg"},
                {"brand_id": 8, "photo_path": "b.jpg"},
            ],
        ),
        encoding="utf-8",
    )
    write_candidate_csv(
        run_dir / "auto_write.csv",
        (("a.jpg", "奥利奥", "7"), ("b.jpg", "元气森林", "8")),
    )
    write_candidate_csv(
        run_dir / "needs_review.csv",
        (("c.jpg", "农夫山泉", "7 9"), ("d.jpg", "可口可乐", "7")),
    )

    summary = filter_run_files(run_dir, (BrandId(7),))

    filtered_auto = json.loads((run_dir / "auto_write.json").read_text(encoding="utf-8"))
    assert [row["brand_id"] for row in filtered_auto] == [8]
    assert summary.auto_write_json_before == 2
    assert summary.auto_write_json_after == 1
    assert read_brand_id_cells(run_dir / "auto_write.csv") == ("8",)
    assert read_brand_id_cells(run_dir / "needs_review.csv") == ("9",)
    assert summary.needs_review_csv_before == 2
    assert summary.needs_review_csv_after == 1


def write_candidate_csv(path: Path, rows: tuple[tuple[str, str, str], ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["photo_path", "detected_text", "confidence", "matched_alias", "brand_ids", "evidence"])
        for photo_path, alias, brand_ids in rows:
            writer.writerow([photo_path, alias, "0.9", alias, brand_ids, "visible"])


def read_brand_id_cells(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(row["brand_ids"] for row in csv.DictReader(handle))


def decoded_queries(call: str) -> tuple[str, ...]:
    url = call.split(" ", maxsplit=1)[1]
    values = parse_qs(urlsplit(url).query).get("queries[]", ())
    return tuple(unquote(value) for value in values)
