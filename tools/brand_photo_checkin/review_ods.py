from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .review_types import Prediction
from .review_workbook import CHECK_OPTIONS, REVIEW_HEADERS

ODS_MIMETYPE: Final = "application/vnd.oasis.opendocument.spreadsheet"


@dataclass(frozen=True, slots=True)
class OdsRow:
    index: int
    photo_path: Path
    prediction: Prediction


def write_review_ods(
    path: Path,
    images: tuple[Path, ...],
    predictions: dict[Path, Prediction],
    brand_options: tuple[str, ...],
) -> None:
    rows = tuple(
        OdsRow(index=index, photo_path=image, prediction=predictions.get(image, Prediction("", "")))
        for index, image in enumerate(images, start=1)
    )
    options = tuple(dict.fromkeys(option for option in brand_options if option.strip()))
    with ZipFile(path, "w") as archive:
        mimetype = ZipInfo("mimetype")
        mimetype.compress_type = ZIP_STORED
        archive.writestr(mimetype, ODS_MIMETYPE)
        archive.writestr("content.xml", content_xml(rows, options), ZIP_DEFLATED)
        archive.writestr("styles.xml", styles_xml(), ZIP_DEFLATED)
        archive.writestr("meta.xml", meta_xml(), ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", manifest_xml(), ZIP_DEFLATED)


def content_xml(rows: tuple[OdsRow, ...], options: tuple[str, ...]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content office:version="1.2" '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
        'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2">'
        f"{automatic_styles_xml()}<office:body><office:spreadsheet>"
        f"{validations_xml(options)}{review_table_xml(rows)}{options_table_xml(options)}"
        "</office:spreadsheet></office:body></office:document-content>"
    )


def validations_xml(options: tuple[str, ...]) -> str:
    _ = options
    return (
        "<table:content-validations>"
        f'<table:content-validation table:name="correct_marker" table:allow-empty-cell="true" '
        f'table:condition={quoteattr(list_condition(CHECK_OPTIONS))}/>'
        "</table:content-validations>"
    )


def list_condition(values: tuple[str, ...]) -> str:
    quoted = ";".join(f'"{value.replace(chr(34), chr(34) * 2)}"' for value in values)
    return f"of:cell-content-is-in-list({quoted})"


def review_table_xml(rows: tuple[OdsRow, ...]) -> str:
    table_rows = [ods_row(tuple(text_cell(header, "header") for header in REVIEW_HEADERS))]
    table_rows.extend(review_row_xml(row) for row in rows)
    return (
        '<table:table table:name="复核">'
        '<table:table-column table:style-name="col-narrow"/>'
        '<table:table-column table:style-name="col-check"/>'
        '<table:table-column table:style-name="col-medium" table:number-columns-repeated="2"/>'
        '<table:table-column table:style-name="col-path"/>'
        f'{"".join(table_rows)}</table:table>'
    )


def review_row_xml(row: OdsRow) -> str:
    return ods_row(
        (
            number_cell(row.index),
            text_cell("", validation="correct_marker"),
            text_cell(row.prediction.matched_alias),
            text_cell(row.prediction.detected_text),
            text_cell(str(row.photo_path), "wrap"),
        ),
    )


def options_table_xml(options: tuple[str, ...]) -> str:
    rows = [ods_row((text_cell("品牌选项", "header"),))]
    rows.extend(ods_row((text_cell(option),)) for option in options)
    return (
        '<table:table table:name="品牌选项" table:visibility="collapse">'
        '<table:table-column table:style-name="col-medium"/>'
        f'{"".join(rows)}</table:table>'
    )


def ods_row(cells: tuple[str, ...]) -> str:
    return f"<table:table-row>{''.join(cells)}</table:table-row>"


def text_cell(value: str, style: str = "", validation: str = "") -> str:
    style_attr = f' table:style-name="{style}"' if style else ""
    validation_attr = f' table:content-validation-name="{validation}"' if validation else ""
    return (
        f'<table:table-cell office:value-type="string"{style_attr}{validation_attr}>'
        f"<text:p>{escape(value)}</text:p></table:table-cell>"
    )


def number_cell(value: int) -> str:
    return f'<table:table-cell office:value-type="float" office:value="{value}"><text:p>{value}</text:p></table:table-cell>'


def automatic_styles_xml() -> str:
    return (
        "<office:automatic-styles>"
        '<style:style style:name="header" style:family="table-cell">'
        '<style:text-properties fo:font-weight="bold" fo:color="#ffffff"/>'
        '<style:table-cell-properties fo:background-color="#1f2937"/>'
        "</style:style>"
        '<style:style style:name="wrap" style:family="table-cell">'
        '<style:table-cell-properties fo:wrap-option="wrap"/>'
        "</style:style>"
        '<style:style style:name="col-narrow" style:family="table-column"><style:table-column-properties style:column-width="1.5cm"/></style:style>'
        '<style:style style:name="col-check" style:family="table-column"><style:table-column-properties style:column-width="2cm"/></style:style>'
        '<style:style style:name="col-medium" style:family="table-column"><style:table-column-properties style:column-width="4.5cm"/></style:style>'
        '<style:style style:name="col-path" style:family="table-column"><style:table-column-properties style:column-width="18cm"/></style:style>'
        "</office:automatic-styles>"
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-styles office:version="1.2" '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"/>'
    )


def meta_xml() -> str:
    now = datetime.now(UTC).isoformat()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-meta office:version="1.2" '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">'
        f"<office:meta><meta:creation-date>{now}</meta:creation-date></office:meta>"
        "</office:document-meta>"
    )


def manifest_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest manifest:version="1.2" '
        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        f'<manifest:file-entry manifest:media-type="{ODS_MIMETYPE}" manifest:full-path="/"/>'
        '<manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>'
        '<manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>'
        '<manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>'
        "</manifest:manifest>"
    )
