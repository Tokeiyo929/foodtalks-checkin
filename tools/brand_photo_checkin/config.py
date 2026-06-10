from __future__ import annotations

import re
from pathlib import Path

from .models import AppwriteConfig


class ConfigError(RuntimeError):
    pass


def read_appwrite_config(path: Path) -> AppwriteConfig:
    text = path.read_text(encoding="utf-8")
    endpoint = read_js_string(text, "endpoint")
    project_id = read_js_string(text, "projectId")
    database_id = read_js_string(text, "databaseId")
    table_id = read_js_string(text, "tableId")
    return AppwriteConfig(
        endpoint=endpoint,
        project_id=project_id,
        database_id=database_id,
        table_id=table_id,
    )


def read_js_string(text: str, key: str) -> str:
    pattern = re.compile(rf"{re.escape(key)}\s*:\s*[\"']([^\"']+)[\"']")
    match = pattern.search(text)
    if match is None:
        msg = f"Missing {key} in appwrite-config.js"
        raise ConfigError(msg)
    return match.group(1)
