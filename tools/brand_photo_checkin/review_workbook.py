from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .review_types import Prediction

REVIEW_HEADERS: Final = ("编号", "正确?", "候选品牌", "识别文字", "图片路径")
CHECK_OPTIONS: Final = ("✓",)


@dataclass(frozen=True, slots=True)
class ReviewWorkbookRow:
    index: int
    photo_path: Path
    prediction: Prediction


def write_review_workbook(
    path: Path,
    images: tuple[Path, ...],
    predictions: dict[Path, Prediction],
    brand_options: tuple[str, ...],
) -> None:
    rows = tuple(
        ReviewWorkbookRow(index=index, photo_path=image, prediction=predictions.get(image, Prediction("", "")))
        for index, image in enumerate(images, start=1)
    )
    options = tuple(dict.fromkeys(option for option in brand_options if option.strip()))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml())
        archive.writestr("_rels/.rels", package_rels_xml())
        archive.writestr("docProps/app.xml", app_props_xml())
        archive.writestr("docProps/core.xml", core_props_xml())
        archive.writestr("xl/workbook.xml", workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml())
        archive.writestr("xl/styles.xml", styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", review_sheet_xml(rows, len(options)))
        archive.writestr("xl/worksheets/sheet2.xml", options_sheet_xml(options))


def review_sheet_xml(rows: tuple[ReviewWorkbookRow, ...], brand_count: int) -> str:
    _ = brand_count
    max_row = max(2, len(rows) + 1)
    sheet_rows = [row_xml(1, tuple(cell_text(1, index + 1, header, 1) for index, header in enumerate(REVIEW_HEADERS)))]
    for row_number, row in enumerate(rows, start=2):
        sheet_rows.append(review_row_xml(row_number, row))
    validations = data_validations_xml(max_row, brand_count)
    return worksheet_xml(
        cols_xml(
            (
                (1, 1, 8),
                (2, 2, 10),
                (3, 4, 24),
                (5, 5, 90),
            ),
        ),
        "\n".join(sheet_rows),
        f'<autoFilter ref="A1:E{max_row}"/>',
        validations,
    )


def review_row_xml(row_number: int, row: ReviewWorkbookRow) -> str:
    values = (
        cell_number(row_number, 1, row.index),
        cell_text(row_number, 2, ""),
        cell_text(row_number, 3, row.prediction.matched_alias),
        cell_text(row_number, 4, row.prediction.detected_text),
        cell_text(row_number, 5, str(row.photo_path), 2),
    )
    return row_xml(row_number, values)


def data_validations_xml(max_row: int, brand_count: int) -> str:
    _ = brand_count
    return (
        '<dataValidations count="1">'
        f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="B2:B{max_row}">'
        '<formula1>"✓"</formula1>'
        "</dataValidation>"
        "</dataValidations>"
    )


def options_sheet_xml(options: tuple[str, ...]) -> str:
    rows = [row_xml(1, (cell_text(1, 1, "品牌选项", 1),))]
    rows.extend(row_xml(index, (cell_text(index, 1, option),)) for index, option in enumerate(options, start=2))
    return worksheet_xml(cols_xml(((1, 1, 36),)), "\n".join(rows), "", "")


def worksheet_xml(cols: str, rows: str, tail: str, validations: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"{cols}<sheetData>{rows}</sheetData>{tail}{validations}</worksheet>"
    )


def row_xml(row_number: int, cells: tuple[str, ...]) -> str:
    return f'<row r="{row_number}">{"".join(cells)}</row>'


def cell_text(row: int, column: int, value: str, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    return (
        f'<c r="{column_name(column)}{row}"{style_attr} t="inlineStr">'
        f"<is><t>{escape(value)}</t></is></c>"
    )


def cell_number(row: int, column: int, value: int) -> str:
    return f'<c r="{column_name(column)}{row}" t="n"><v>{value}</v></c>'


def column_name(index: int) -> str:
    name = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cols_xml(widths: tuple[tuple[int, int, int], ...]) -> str:
    columns = "".join(f'<col min="{start}" max="{end}" width="{width}" customWidth="1"/>' for start, end, width in widths)
    return f"<cols>{columns}</cols>"


def workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="复核" sheetId="1" r:id="rId1"/>'
        '<sheet name="品牌选项" sheetId="2" state="hidden" r:id="rId2"/>'
        "</sheets></workbook>"
    )


def workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="10"/><name val="Noto Sans SC"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Noto Sans SC"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F2937"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border>'
        '</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf></cellXfs>'
        "</styleSheet>"
    )


def content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def package_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def app_props_xml() -> str:
    return '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>FoodTalks Checkin</Application></Properties>'


def core_props_xml() -> str:
    now = datetime.now(UTC).isoformat()
    return (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>FoodTalks Checkin</dc:creator><dc:title>照片品牌复核</dc:title>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )
