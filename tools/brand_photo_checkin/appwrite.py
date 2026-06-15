from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .local_env import load_local_env
from .models import AppwriteConfig, BrandId, JsonValue


class AppwriteError(RuntimeError):
    pass


class HttpTransport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: JsonValue | None,
    ) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class UrlLibTransport:
    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: JsonValue | None,
    ) -> JsonValue:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            msg = f"Appwrite HTTP {error.code}: {details}"
            raise AppwriteError(msg) from error
        except urllib.error.URLError as error:
            msg = f"Appwrite request failed: {error}"
            raise AppwriteError(msg) from error


@dataclass(frozen=True, slots=True)
class AppwriteClient:
    config: AppwriteConfig
    api_key: str
    transport: HttpTransport

    @classmethod
    def from_env(cls, config: AppwriteConfig) -> "AppwriteClient":
        load_local_env()
        api_key = os.environ.get("APPWRITE_API_KEY", "").strip()
        if not api_key:
            msg = "APPWRITE_API_KEY is required"
            raise AppwriteError(msg)
        return cls(config=config, api_key=api_key, transport=UrlLibTransport())

    def upsert_checkin(self, user_id: str, brand_id: BrandId, checked_at: str) -> JsonValue:
        existing = self.find_checkin(user_id, brand_id)
        row_data: dict[str, JsonValue] = {
            "user_id": user_id,
            "brand_id": int(brand_id),
            "checked_at": checked_at,
        }
        payload: JsonValue = {
            "data": row_data,
            "permissions": user_permissions(user_id),
        }
        match existing:
            case {"rows": [dict(row), *_]} if "$id" in row:
                return self.send(
                    "PATCH",
                    f"{self.rows_url()}/{urllib.parse.quote(str(row['$id']))}",
                    payload,
                )
            case _:
                create_payload: JsonValue = {
                    "rowId": uuid.uuid4().hex,
                    "data": row_data,
                    "permissions": user_permissions(user_id),
                }
                return self.send("POST", self.rows_url(), create_payload)

    def find_checkin(self, user_id: str, brand_id: BrandId) -> JsonValue:
        queries = [
            query_equal("user_id", user_id),
            query_equal("brand_id", int(brand_id)),
            query_limit(1),
        ]
        query = urllib.parse.urlencode([("queries[]", value) for value in queries])
        return self.send("GET", f"{self.rows_url()}?{query}", None)

    def list_checked_brand_ids(self, user_id: str, page_size: int = 100) -> tuple[BrandId, ...]:
        brand_ids: list[BrandId] = []
        offset = 0
        while True:
            rows = self.list_checkins_page(user_id, page_size, offset)
            if not rows:
                break
            brand_ids.extend(brand_id for brand_id in rows if brand_id not in brand_ids)
            if len(rows) < page_size:
                break
            offset += page_size
        return tuple(brand_ids)

    def list_checkins_page(self, user_id: str, limit: int, offset: int) -> tuple[BrandId, ...]:
        queries = [
            query_equal("user_id", user_id),
            query_limit(limit),
            query_offset(offset),
        ]
        query = urllib.parse.urlencode([("queries[]", value) for value in queries])
        response = self.send("GET", f"{self.rows_url()}?{query}", None)
        return checked_brand_ids_from_response(response)

    def send(self, method: str, url: str, body: JsonValue | None) -> JsonValue:
        return self.transport.send(method, url, self.headers(), body)

    def rows_url(self) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        database = urllib.parse.quote(self.config.database_id)
        table = urllib.parse.quote(self.config.table_id)
        return f"{endpoint}/tablesdb/{database}/tables/{table}/rows"

    def headers(self) -> dict[str, str]:
        return {
            "X-Appwrite-Project": self.config.project_id,
            "X-Appwrite-Key": self.api_key,
            "Content-Type": "application/json",
        }


def query_equal(field: str, value: str | int) -> str:
    return query_object("equal", field, [value])


def query_limit(value: int) -> str:
    return query_object("limit", None, [value])


def query_offset(value: int) -> str:
    return query_object("offset", None, [value])


def query_object(method: str, field: str | None, values: list[JsonValue]) -> str:
    payload: dict[str, JsonValue] = {"method": method, "values": values}
    if field is not None:
        payload["attribute"] = field
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def user_permissions(user_id: str) -> list[JsonValue]:
    return [
        f'read("user:{user_id}")',
        f'update("user:{user_id}")',
        f'delete("user:{user_id}")',
    ]


def checked_brand_ids_from_response(response: JsonValue) -> tuple[BrandId, ...]:
    parsed: list[BrandId] = []
    match response:
        case {"rows": list(rows)}:
            for row in rows:
                match row:
                    case {"brand_id": int(brand_id)}:
                        parsed.append(BrandId(brand_id))
                    case {"data": {"brand_id": int(brand_id)}}:
                        parsed.append(BrandId(brand_id))
                    case _:
                        continue
            return tuple(parsed)
        case _:
            msg = "Appwrite list response did not contain rows"
            raise AppwriteError(msg)
