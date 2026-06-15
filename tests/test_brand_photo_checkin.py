from __future__ import annotations

import json
import os
from pathlib import Path

from pytest import MonkeyPatch

import tools.brand_photo_checkin.__main__ as checkin_cli
from tools.brand_photo_checkin.appwrite import AppwriteClient, query_equal, query_limit, user_permissions
from tools.brand_photo_checkin.brands import find_candidates, match_visible_brands, normalize_text
from tools.brand_photo_checkin.feedback import FeedbackRow, approve_feedback, parse_feedback_row, read_feedback_ods
from tools.brand_photo_checkin.local_env import load_local_env
from tools.brand_photo_checkin.models import (
    AppwriteConfig,
    BrandId,
    BrandRecord,
    JsonValue,
    PhotoRecord,
    VisibleBrand,
)
from tools.brand_photo_checkin.openai_batch import OpenAIClient, build_batch_request, parse_visible_brands
from tools.brand_photo_checkin.openai_batch import response_body_from_batch_request
from tools.brand_photo_checkin.photos import discover_images
from tools.brand_photo_checkin.progress import write_progress
from tools.brand_photo_checkin import progress as progress_module
from tools.brand_photo_checkin.review_pack import select_review_images, write_feedback_csv
from tools.brand_photo_checkin.review_ods import ODS_MIMETYPE, write_review_ods
from tools.brand_photo_checkin.review_types import Prediction
from tools.brand_photo_checkin.review_workbook import write_review_workbook


class FakeTransport:
    def __init__(self, first_response: JsonValue) -> None:
        self.first_response: JsonValue = first_response
        self.calls: list[tuple[str, str, JsonValue | None]] = []

    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: JsonValue | None,
    ) -> JsonValue:
        _ = headers
        self.calls.append((method, url, body))
        if len(self.calls) == 1:
            return self.first_response
        return {"ok": True}


class FakeOpenAIResponseClient:
    def __init__(self, fail_on_call: int | None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[str] = []

    def create_response(self, body: JsonValue) -> JsonValue:
        match body:
            case {"model": str(model)}:
                self.calls.append(model)
            case _:
                self.calls.append("unknown")
        if len(self.calls) == self.fail_on_call:
            raise ConnectionResetError("simulated reset")
        return {"output_text": '{"visible_brand_names":[],"notes":""}'}


def brand_row(brand_id: int, company: str, brands: tuple[str, ...] = ()) -> BrandRecord:
    return BrandRecord(
        id=BrandId(brand_id),
        primary="饮料",
        secondary="茶",
        tertiary="茶饮料",
        company=company,
        brands=brands,
    )


def test_normalize_text_when_chinese_brand_has_punctuation() -> None:
    assert normalize_text(" 元气森林（外星人） ") == "元气森林外星人"


def test_find_candidates_when_company_is_duplicated_keeps_all_brand_ids() -> None:
    brands = (brand_row(1, "农夫山泉"), brand_row(2, "农夫山泉"))
    alias_index = {"农夫山泉": brands}

    candidates = find_candidates("农夫山泉", alias_index)

    assert tuple(int(row.id) for row in candidates[0][1]) == (1, 2)


def test_match_visible_brands_when_duplicate_company_needs_review() -> None:
    brands = (brand_row(1, "农夫山泉"), brand_row(2, "农夫山泉"))
    visible = (VisibleBrand(text="农夫山泉", confidence=0.99, evidence="logo readable"),)

    report = match_visible_brands(Path("a.jpg"), visible, brands, auto_threshold=0.8)

    assert report.auto_write == ()
    assert tuple(int(item) for item in report.needs_review[0].brand_ids) == (1, 2)


def test_match_visible_brands_when_unique_brand_above_threshold_auto_writes() -> None:
    brands = (brand_row(5, "元气森林", ("外星人",)),)
    visible = (VisibleBrand(text="外星人", confidence=0.91, evidence="can label"),)

    report = match_visible_brands(Path("b.jpg"), visible, brands, auto_threshold=0.8)

    assert tuple(int(item) for item in report.auto_write[0].brand_ids) == (5,)
    assert report.needs_review == ()


def test_build_batch_request_contains_structured_response_schema(tmp_path: Path) -> None:
    preview = tmp_path / "preview.jpg"
    _ = preview.write_bytes(b"fake")
    record = PhotoRecord(
        custom_id="photo-1",
        path=tmp_path / "source.jpg",
        preview_path=preview,
        size_bytes=4,
        modified_ns=1,
        sha256="abc",
    )

    request = build_batch_request(record, "gpt-5.4-mini", "low")

    match request:
        case {"body": {"text": {"format": {"type": "json_schema", "strict": True}}}}:
            schema_found = True
        case _:
            raise AssertionError("missing structured output schema")
    assert schema_found


def test_openai_client_url_when_base_url_has_trailing_slash() -> None:
    client = OpenAIClient(api_key="key", base_url="http://localhost:8317/v1/")

    assert client.url("/models") == "http://localhost:8317/v1/models"


def test_response_body_from_batch_request_extracts_body() -> None:
    row: JsonValue = {"custom_id": "photo-1", "body": {"model": "gpt-5.4-mini"}}

    body = response_body_from_batch_request(row)

    assert body == {"model": "gpt-5.4-mini"}


def test_run_sync_keeps_partial_output_and_resumes_after_reset(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    requests = (
        {"custom_id": "photo-1", "body": {"model": "first"}},
        {"custom_id": "photo-2", "body": {"model": "second"}},
    )
    request_path = tmp_path / "batch_requests.jsonl"
    request_path.write_text("\n".join(json.dumps(row) for row in requests) + "\n", encoding="utf-8")
    first_client = FakeOpenAIResponseClient(fail_on_call=2)
    monkeypatch.setattr(checkin_cli.OpenAIClient, "from_env", lambda: first_client)

    try:
        checkin_cli.run_sync(tmp_path, retries=0, retry_delay_seconds=0.0)
    except ConnectionResetError:
        pass

    output_path = tmp_path / "batch_output.jsonl"
    first_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [row["custom_id"] for row in first_rows] == ["photo-1"]

    second_client = FakeOpenAIResponseClient(fail_on_call=None)
    monkeypatch.setattr(checkin_cli.OpenAIClient, "from_env", lambda: second_client)
    checkin_cli.run_sync(tmp_path, retries=0, retry_delay_seconds=0.0)

    resumed_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [row["custom_id"] for row in resumed_rows] == ["photo-1", "photo-2"]
    assert second_client.calls == ["second"]
    progress_text = (tmp_path / "progress.txt").read_text(encoding="utf-8")
    assert "progress: 2/2 (100.0%)" in progress_text


def test_run_sync_writes_progress_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    requests = (
        {"custom_id": "photo-1", "body": {"model": "first"}},
        {"custom_id": "photo-2", "body": {"model": "second"}},
    )
    request_path = tmp_path / "batch_requests.jsonl"
    request_path.write_text("\n".join(json.dumps(row) for row in requests) + "\n", encoding="utf-8")
    client = FakeOpenAIResponseClient(fail_on_call=None)
    monkeypatch.setattr(checkin_cli.OpenAIClient, "from_env", lambda: client)

    checkin_cli.run_sync(tmp_path, retries=0, retry_delay_seconds=0.0)

    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["total"] == 2
    assert progress["completed"] == 2
    assert progress["skipped"] == 0
    assert "100.0%" in (tmp_path / "progress.txt").read_text(encoding="utf-8")


def test_write_progress_when_text_file_is_locked_keeps_json_progress(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def raise_locked_file(path: Path, text: str) -> None:
        _ = (path, text)
        raise PermissionError("locked by reader")

    monkeypatch.setattr(progress_module, "write_text_atomic", raise_locked_file)

    write_progress(
        tmp_path,
        phase="run-sync",
        status="running",
        total=2,
        completed=1,
        skipped=0,
        failed=0,
        current_id="photo-1",
        message="Processing photo-1.",
    )

    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert progress["current_id"] == "photo-1"


def test_discover_images_when_offset_and_limit_are_set(tmp_path: Path) -> None:
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        _ = (tmp_path / name).write_bytes(b"x")

    files = discover_images(tmp_path, limit=1, offset=1)

    assert files == (tmp_path / "b.jpg",)


def test_write_feedback_csv_includes_review_index_and_prediction(tmp_path: Path) -> None:
    image = tmp_path / "a.jpg"
    _ = image.write_bytes(b"x")
    output = tmp_path / "review_feedback.csv"
    predictions = {image: Prediction(detected_text="奥利奥", matched_alias="奥利奥")}

    write_feedback_csv(output, (image,), predictions)

    rows = output.read_text(encoding="utf-8-sig").splitlines()
    assert rows[0] == "index,correct,matched_alias,detected_text,photo_path"
    assert rows[1] == f"1,,奥利奥,奥利奥,{image}"


def test_select_review_images_when_run_dir_exists_uses_only_predictions(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.jpg"
    ignored = tmp_path / "ignored.jpg"
    _ = candidate.write_bytes(b"x")
    _ = ignored.write_bytes(b"x")
    predictions = {candidate: Prediction(detected_text="奥利奥", matched_alias="奥利奥")}

    images = select_review_images(tmp_path, tmp_path / "run", predictions, limit=None, offset=0)

    assert images == (candidate,)


def test_write_review_workbook_includes_dropdown_validations(tmp_path: Path) -> None:
    image = tmp_path / "a.jpg"
    _ = image.write_bytes(b"x")
    output = tmp_path / "review_feedback.xlsx"
    predictions = {image: Prediction(detected_text="奥利奥", matched_alias="奥利奥")}

    write_review_workbook(output, (image,), predictions, ("奥利奥", "元气森林"))

    import zipfile

    with zipfile.ZipFile(output) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "dataValidations" in sheet_xml
    assert '"✓"' in sheet_xml
    assert "sqref=\"B2:B2\"" in sheet_xml


def test_write_review_ods_leaves_check_cells_blank_by_default(tmp_path: Path) -> None:
    image = tmp_path / "a.jpg"
    _ = image.write_bytes(b"x")
    output = tmp_path / "review_feedback.ods"
    checked_output = tmp_path / "review_feedback_checked.ods"
    predictions = {image: Prediction(detected_text="奥利奥", matched_alias="奥利奥")}

    write_review_ods(output, (image,), predictions, ("奥利奥", "元气森林"))

    import zipfile

    with zipfile.ZipFile(output) as archive:
        assert archive.read("mimetype").decode("utf-8") == ODS_MIMETYPE
        content_xml = archive.read("content.xml").decode("utf-8")
        entries = {name: archive.read(name) for name in archive.namelist()}
    assert "table:content-validations" not in content_xml
    assert "correct_marker" not in content_xml
    assert "FALSE" not in content_xml
    assert 'office:boolean-value="false"' not in content_xml
    assert "备注" not in content_xml
    assert "奥利奥" in content_xml
    entries["content.xml"] = content_xml.replace(
        '<table:table-cell table:style-name="check"><text:p></text:p></table:table-cell>',
        '<table:table-cell office:value-type="string" table:style-name="check"><text:p>TRUE</text:p></table:table-cell>',
        1,
    ).encode("utf-8")
    with zipfile.ZipFile(checked_output, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    assert read_feedback_ods(checked_output)[0].correct_marker == "TRUE"


def test_approve_feedback_when_checked_uses_candidate_brand(tmp_path: Path) -> None:
    rows = (
        FeedbackRow(1, "✓", "", "奥利奥", tmp_path / "a.jpg"),
        FeedbackRow(2, "", "", "元气森林", tmp_path / "b.jpg"),
    )
    brands = (brand_row(7, "亿滋", ("奥利奥",)), brand_row(8, "元气森林"))

    approved = approve_feedback(rows, brands)

    assert len(approved) == 1
    assert int(approved[0].brand_id) == 7
    assert approved[0].photo_path == tmp_path / "a.jpg"


def test_approve_feedback_when_unchecked_with_note_uses_note_brand(tmp_path: Path) -> None:
    rows = (FeedbackRow(1, "", "元气森林", "奥利奥", tmp_path / "a.jpg"),)
    brands = (brand_row(7, "亿滋", ("奥利奥",)), brand_row(8, "元气森林"))

    approved = approve_feedback(rows, brands)

    assert len(approved) == 1
    assert int(approved[0].brand_id) == 8


def test_approve_feedback_when_checked_only_ignores_unchecked_notes(tmp_path: Path) -> None:
    rows = (
        FeedbackRow(1, "✓", "", "奥利奥", tmp_path / "a.jpg"),
        FeedbackRow(2, "", "元气森林", "奥利奥", tmp_path / "b.jpg"),
    )
    brands = (brand_row(7, "亿滋", ("奥利奥",)), brand_row(8, "元气森林"))

    approved = approve_feedback(rows, brands, checked_only=True)

    assert len(approved) == 1
    assert int(approved[0].brand_id) == 7


def test_approve_feedback_when_candidate_alias_duplicates_same_brand_id(tmp_path: Path) -> None:
    rows = (FeedbackRow(1, "✓", "", "奥利奥", tmp_path / "a.jpg"),)
    duplicated = brand_row(7, "亿滋", ("奥利奥",))
    brands = (duplicated, duplicated)

    approved = approve_feedback(rows, brands, checked_only=True)

    assert len(approved) == 1
    assert int(approved[0].brand_id) == 7


def test_approve_feedback_when_skip_unresolved_ignores_ambiguous_checked_row(tmp_path: Path) -> None:
    rows = (FeedbackRow(1, "✓", "", "农夫山泉", tmp_path / "a.jpg"),)
    brands = (brand_row(1, "农夫山泉"), brand_row(2, "农夫山泉"))

    approved = approve_feedback(rows, brands, checked_only=True, skip_unresolved=True)

    assert approved == ()


def test_parse_feedback_row_when_old_ods_shifted_path_left() -> None:
    headers = ("编号", "正确?", "备注", "候选品牌", "识别文字", "图片路径")
    row = (
        "1",
        "✓",
        "blueglassyogurt阿秋拉尕酸奶",
        "Blueglass",
        r"C:\Users\addAdministrators\Pictures\photos\相册\IMG_0059(1).heic",
        "",
    )

    parsed = parse_feedback_row(row, headers)

    assert parsed.note == ""
    assert parsed.candidate_brand == "Blueglass"
    assert parsed.photo_path == Path(r"C:\Users\addAdministrators\Pictures\photos\相册\IMG_0059(1).heic")


def test_parse_feedback_row_when_new_ods_has_no_note_column() -> None:
    headers = ("编号", "正确?", "候选品牌", "识别文字", "图片路径")
    row = ("1", "✓", "Blueglass", "blueglassyogurt阿秋拉尕酸奶", "a.heic")

    parsed = parse_feedback_row(row, headers)

    assert parsed.note == ""
    assert parsed.candidate_brand == "Blueglass"
    assert parsed.photo_path == Path("a.heic")


def test_read_approved_rows_deduplicates_brand_ids(tmp_path: Path) -> None:
    approved = tmp_path / "approved_feedback.json"
    approved.write_text(
        json.dumps([{"brand_id": 7}, {"brand_id": 7}, {"brand_id": 8}], ensure_ascii=False),
        encoding="utf-8",
    )

    rows = checkin_cli.read_approved_rows(approved)

    assert tuple(int(row) for row in rows) == (7, 8)


def test_load_local_env_uses_file_values_without_overriding_existing_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    env_path = tmp_path / "foodtalks.env"
    env_path.write_text("OPENAI_API_KEY=file-key\nAPPWRITE_USER_ID=file-user\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    monkeypatch.delenv("APPWRITE_USER_ID", raising=False)

    load_local_env(env_path)

    assert os.environ["OPENAI_API_KEY"] == "process-key"
    assert os.environ["APPWRITE_USER_ID"] == "file-user"


def test_parse_visible_brands_when_response_has_output_text() -> None:
    body: JsonValue = {
        "output_text": json.dumps(
            {
                "visible_brand_names": [
                    {"text": "喜茶", "confidence": 0.95, "evidence": "shop sign"},
                ],
                "notes": "",
            },
        ),
    }

    visible = parse_visible_brands(body)

    assert visible[0].text == "喜茶"
    assert visible[0].confidence == 0.95


def test_query_equal_matches_appwrite_rest_syntax() -> None:
    assert query_equal("brand_id", 5) == '{"method":"equal","values":[5],"attribute":"brand_id"}'
    assert query_equal("user_id", "abc") == '{"method":"equal","values":["abc"],"attribute":"user_id"}'
    assert query_limit(1) == '{"method":"limit","values":[1]}'


def test_appwrite_upsert_updates_existing_row() -> None:
    transport = FakeTransport({"rows": [{"$id": "row-1"}]})
    client = AppwriteClient(
        config=AppwriteConfig(
            endpoint="https://example.appwrite.io/v1",
            project_id="project",
            database_id="db",
            table_id="table",
        ),
        api_key="key",
        transport=transport,
    )

    _ = client.upsert_checkin("user-1", BrandId(7), "2026-06-08T00:00:00Z")

    assert transport.calls[1][0] == "PATCH"
    assert transport.calls[1][2] == {
        "data": {
            "user_id": "user-1",
            "brand_id": 7,
            "checked_at": "2026-06-08T00:00:00Z",
        },
        "permissions": user_permissions("user-1"),
    }


def test_appwrite_upsert_creates_missing_row() -> None:
    transport = FakeTransport({"rows": []})
    client = AppwriteClient(
        config=AppwriteConfig(
            endpoint="https://example.appwrite.io/v1",
            project_id="project",
            database_id="db",
            table_id="table",
        ),
        api_key="key",
        transport=transport,
    )

    _ = client.upsert_checkin("user-1", BrandId(8), "2026-06-08T00:00:00Z")

    assert transport.calls[1][0] == "POST"
    match transport.calls[1][2]:
        case {"data": {"brand_id": 8}, "permissions": list()}:
            assert True
        case _:
            raise AssertionError("missing create payload")
