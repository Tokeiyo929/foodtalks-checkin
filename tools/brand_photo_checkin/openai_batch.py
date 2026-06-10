from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .local_env import load_local_env
from .models import JsonValue, PhotoRecord, VisibleBrand

DEFAULT_OPENAI_BASE_URL: Final = "https://api.openai.com/v1"


class OpenAIRequestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OpenAIClient:
    api_key: str
    base_url: str

    @classmethod
    def from_env(cls) -> "OpenAIClient":
        load_local_env()
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            msg = "OPENAI_API_KEY is required"
            raise OpenAIRequestError(msg)
        return cls(api_key=api_key, base_url=read_base_url())

    def upload_batch_file(self, path: Path) -> str:
        boundary = "----foodtalks-openai-boundary"
        body = multipart_body(boundary, path)
        request = urllib.request.Request(
            self.url("/files"),
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        data = send_json_request(request)
        match data:
            case {"id": str(file_id)}:
                return file_id
            case _:
                msg = f"OpenAI file upload returned unexpected payload: {data!r}"
                raise OpenAIRequestError(msg)

    def create_batch(self, input_file_id: str) -> str:
        body = json.dumps(
            {
                "input_file_id": input_file_id,
                "endpoint": "/v1/responses",
                "completion_window": "24h",
            },
        ).encode()
        request = urllib.request.Request(
            self.url("/batches"),
            data=body,
            headers=self.json_headers(),
            method="POST",
        )
        data = send_json_request(request)
        match data:
            case {"id": str(batch_id)}:
                return batch_id
            case _:
                msg = f"OpenAI batch creation returned unexpected payload: {data!r}"
                raise OpenAIRequestError(msg)

    def create_response(self, body: JsonValue) -> JsonValue:
        request = urllib.request.Request(
            self.url("/responses"),
            data=json.dumps(body).encode(),
            headers=self.json_headers(),
            method="POST",
        )
        return send_json_request(request)

    def get_batch(self, batch_id: str) -> JsonValue:
        request = urllib.request.Request(
            self.url(f"/batches/{batch_id}"),
            headers=self.json_headers(),
            method="GET",
        )
        return send_json_request(request)

    def download_file(self, file_id: str, target: Path) -> None:
        request = urllib.request.Request(
            self.url(f"/files/{file_id}/content"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                target.parent.mkdir(parents=True, exist_ok=True)
                _ = target.write_bytes(response.read())
        except urllib.error.URLError as error:
            msg = f"Failed to download OpenAI file {file_id}: {error}"
            raise OpenAIRequestError(msg) from error

    def json_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


def read_base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")


def build_batch_request(record: PhotoRecord, model: str, image_detail: str) -> JsonValue:
    image_url = preview_data_url(record.preview_path)
    return {
        "custom_id": record.custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": detection_prompt()},
                        {"type": "input_image", "image_url": image_url, "detail": image_detail},
                    ],
                },
            ],
            "text": {"format": response_schema()},
            "max_output_tokens": 700,
        },
    }


def response_body_from_batch_request(request: JsonValue) -> JsonValue:
    match request:
        case {"body": dict(body)}:
            return body
        case _:
            msg = f"Invalid batch request row: {request!r}"
            raise OpenAIRequestError(msg)


def detection_prompt() -> str:
    return (
        "Identify readable food or beverage brand names visible in this photo. "
        "Count packaging, signs, receipts, menus, posters, and shelf labels. "
        "Do not guess brands that are not readable. Return Chinese or English text exactly as seen."
    )


def response_schema() -> JsonValue:
    return {
        "type": "json_schema",
        "name": "photo_brand_detection",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["visible_brand_names", "notes"],
            "properties": {
                "visible_brand_names": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["text", "confidence", "evidence"],
                        "properties": {
                            "text": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence": {"type": "string"},
                        },
                    },
                },
                "notes": {"type": "string"},
            },
        },
    }


def preview_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def parse_visible_brands(response_body: JsonValue) -> tuple[VisibleBrand, ...]:
    payload = extract_output_json(response_body)
    match payload:
        case {"visible_brand_names": list(items)}:
            return tuple(parse_visible_brand(item) for item in items)
        case _:
            return ()


def parse_visible_brand(raw: JsonValue) -> VisibleBrand:
    match raw:
        case {"text": str(text), "confidence": int(confidence), "evidence": str(evidence)}:
            return VisibleBrand(text=text, confidence=float(confidence), evidence=evidence)
        case {"text": str(text), "confidence": float(confidence), "evidence": str(evidence)}:
            return VisibleBrand(text=text, confidence=confidence, evidence=evidence)
        case _:
            return VisibleBrand(text="", confidence=0.0, evidence="invalid structured item")


def extract_output_json(response_body: JsonValue) -> JsonValue:
    match response_body:
        case {"output_text": str(text)}:
            return json.loads(text)
        case {"output": list(outputs)}:
            for output in outputs:
                match output:
                    case {"content": list(contents)}:
                        for content in contents:
                            match content:
                                case {"text": str(text)}:
                                    return json.loads(text)
                                case _:
                                    continue
                    case _:
                        continue
        case _:
            return {}
    return {}


def multipart_body(boundary: str, path: Path) -> bytes:
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        "batch\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/jsonl\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    return prefix + path.read_bytes() + suffix


def send_json_request(request: urllib.request.Request) -> JsonValue:
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        msg = f"OpenAI API HTTP {error.code}: {details}"
        raise OpenAIRequestError(msg) from error
    except urllib.error.URLError as error:
        msg = f"OpenAI API request failed: {error}"
        raise OpenAIRequestError(msg) from error
