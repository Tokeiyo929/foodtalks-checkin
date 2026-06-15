from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING, Final

import typer

from .brands import load_brands
from .photos import discover_images
from .review_ods import write_review_ods
from .review_types import Prediction

if TYPE_CHECKING:
    from PIL.Image import Image as PillowImage
    from PIL.ImageDraw import ImageDraw
    from PIL.ImageFont import FreeTypeFont, ImageFont

CELL_SIZE: Final = 360
LABEL_HEIGHT: Final = 68
DEFAULT_COLUMNS: Final = 5

app = typer.Typer(no_args_is_help=True)


@app.command()
def create(
    photos: Path = typer.Argument(..., help="Photo file or folder to review."),
    output_dir: Path = typer.Option(..., help="Review pack output folder."),
    run_dir: Path | None = typer.Option(None, help="Optional run dir with auto/review CSV reports."),
    brand_data: Path = typer.Option(Path("brand-checkin-data.js"), help="Path to brand-checkin-data.js."),
    limit: int | None = typer.Option(None, help="Optional max photo count."),
    offset: int = typer.Option(0, help="Number of sorted photos to skip."),
    columns: int = typer.Option(DEFAULT_COLUMNS, help="Contact sheet columns."),
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions = load_predictions(run_dir)
    images = select_review_images(photos, run_dir, predictions, limit, offset)
    write_review_ods(output_dir / "review_feedback.ods", images, predictions, brand_options(brand_data))
    write_instructions(output_dir / "README.txt")
    write_contact_sheet(output_dir / "contact-sheet-001.jpg", images, predictions, columns)
    typer.echo(f"Wrote review pack for {len(images)} photos to {output_dir}")


def load_predictions(run_dir: Path | None) -> dict[Path, Prediction]:
    if run_dir is None:
        return {}
    predictions: dict[Path, Prediction] = {}
    for name in ("auto_write.csv", "needs_review.csv"):
        path = run_dir / name
        if path.exists():
            predictions.update(read_prediction_csv(path))
    return predictions


def brand_options(brand_data: Path) -> tuple[str, ...]:
    names: list[str] = []
    for brand in load_brands(brand_data):
        names.extend(brand.brands or (brand.company,))
    return tuple(sorted(dict.fromkeys(name for name in names if name)))


def select_review_images(
    photos: Path,
    run_dir: Path | None,
    predictions: dict[Path, Prediction],
    limit: int | None,
    offset: int,
) -> tuple[Path, ...]:
    if run_dir is not None:
        return tuple(predictions)
    return discover_images(photos, limit, offset)


def read_prediction_csv(path: Path) -> dict[Path, Prediction]:
    rows: dict[Path, Prediction] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            photo_path = row.get("photo_path", "").strip()
            if not photo_path:
                continue
            rows[Path(photo_path)] = Prediction(
                detected_text=row.get("detected_text", "").strip(),
                matched_alias=row.get("matched_alias", "").strip(),
            )
    return rows


def write_feedback_csv(path: Path, images: tuple[Path, ...], predictions: dict[Path, Prediction]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "correct", "matched_alias", "detected_text", "photo_path"])
        for index, image in enumerate(images, start=1):
            prediction = predictions.get(image, Prediction("", ""))
            writer.writerow([index, "", prediction.matched_alias, prediction.detected_text, str(image)])


def write_instructions(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "请优先打开 review_feedback.ods，在“正确?”列输入 TRUE 或 ✓，保存不弹格式警告。",
                "这里仅包含流程判断可能有 FoodTalks 品牌的照片；没进来的默认不用核对。",
                "如果候选品牌正确，就把“正确?”列标成 TRUE 或 ✓。",
                "如果候选品牌不正确，就保持空白；空白不会写入 Appwrite。",
            ],
        ),
        encoding="utf-8",
    )


def write_contact_sheet(
    path: Path,
    images: tuple[Path, ...],
    predictions: dict[Path, Prediction],
    columns: int,
) -> None:
    from PIL import Image, ImageDraw
    from pillow_heif import register_heif_opener

    register_heif_opener()
    safe_columns = max(1, columns)
    rows = (len(images) + safe_columns - 1) // safe_columns
    sheet = Image.new("RGB", (safe_columns * CELL_SIZE, rows * (CELL_SIZE + LABEL_HEIGHT)), "white")
    draw = ImageDraw.Draw(sheet)
    font = load_label_font()
    for index, image_path in enumerate(images, start=1):
        x = ((index - 1) % safe_columns) * CELL_SIZE
        y = ((index - 1) // safe_columns) * (CELL_SIZE + LABEL_HEIGHT)
        draw_cell(sheet, draw, image_path, predictions.get(image_path), index, x, y, font)
    sheet.save(path, "JPEG", quality=95, optimize=True)


def load_label_font() -> ImageFont | FreeTypeFont:
    from PIL import ImageFont

    for font_path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if font_path.exists():
            return ImageFont.truetype(str(font_path), 20)
    return ImageFont.load_default()


def draw_cell(
    sheet: PillowImage,
    draw: ImageDraw,
    image_path: Path,
    prediction: Prediction | None,
    index: int,
    x: int,
    y: int,
    font: ImageFont | FreeTypeFont,
) -> None:
    from PIL import Image, ImageOps, UnidentifiedImageError

    image_box = (x, y, x + CELL_SIZE, y + CELL_SIZE)
    try:
        with Image.open(image_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            image.thumbnail((CELL_SIZE, CELL_SIZE))
            paste_x = x + (CELL_SIZE - image.width) // 2
            paste_y = y + (CELL_SIZE - image.height) // 2
            sheet.paste(image, (paste_x, paste_y))
    except (OSError, UnidentifiedImageError):
        draw.rectangle(image_box, fill="#eeeeee")
        draw.text((x + 8, y + 8), "unreadable", fill="red", font=font)
    draw.rectangle(image_box, outline="#cccccc", width=1)
    label = label_text(index, prediction)
    draw.rectangle((x, y + CELL_SIZE, x + CELL_SIZE, y + CELL_SIZE + LABEL_HEIGHT), fill="#111111")
    draw.text((x + 8, y + CELL_SIZE + 8), label, fill="white", font=font)


def label_text(index: int, prediction: Prediction | None) -> str:
    prefix = f"#{index:03d}"
    if prediction is None or not prediction.matched_alias:
        return prefix
    return f"{prefix} guess: {prediction.matched_alias[:24]}"


if __name__ == "__main__":
    app()
