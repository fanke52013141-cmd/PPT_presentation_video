"""Keep generated bitmap content inside the configured body area without cutting it."""

from pathlib import Path

from PIL import Image, ImageChops

from ai_mask_contracts import mask_source_raw_path
from ai_provider_service import save_image_atomically


def fit_generated_body_to_safe_area(image_path, area):
    """Fit an overflowing page uniformly; preserve layout and raw alignment.

    This runs before publication, only on generated candidates. The body is
    never redrawn. Both saved source variants receive the identical transform.
    """
    path = Path(image_path)
    left, top, right, bottom = (int(area[key]) for key in ("left", "top", "right", "bottom"))
    with Image.open(path) as source:
        image = source.convert("RGB")
    if not (0 <= left < right <= image.width and 0 <= top < bottom < image.height):
        raise ValueError("正文安全区不在图片画布内")
    red, green, blue = image.split()
    mask = ImageChops.darker(ImageChops.darker(red, green), blue).point(lambda value: 255 if value < 248 else 0)
    bounds = mask.getbbox()
    if bounds is None or bounds[3] <= bottom:
        return False
    x1, y1, x2, y2 = bounds
    # Fit the whole bitmap's content together: models sometimes put card tops
    # above the nominal body boundary. Slicing there would split those cards.
    page_top = min(60, top)
    scale = min(1.0, (right - left) / (x2 - x1), (bottom - page_top) / (y2 - y1))
    width, height = max(1, int((x2 - x1) * scale)), max(1, int((y2 - y1) * scale))
    destination = (left + (right - left - width) // 2, page_top)
    crop = bounds
    variants = [path]
    raw = mask_source_raw_path(path)
    if raw.exists():
        variants.append(raw)
    for variant in variants:
        with Image.open(variant) as source:
            original = source.convert("RGB")
        if original.size != image.size:
            raise ValueError("原始素材画布与主图不匹配")
        fitted = original.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
        original.paste("white", (0, 0, original.width, original.height))
        original.paste(fitted, destination)
        save_image_atomically(original, str(variant))
    return True
