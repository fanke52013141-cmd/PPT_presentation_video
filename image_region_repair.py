"""Pixel-preserving regional application of reviewed image candidates."""

from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field, StrictInt, model_validator

from ai_mask_contracts import mask_source_raw_path, resolve_mask_source_master, seal_mask_source_pair
from artifact_fingerprint import sha256_file


class ImageCandidateApplyPayload(BaseModel):
    slide_id: str = Field(min_length=1)
    disposition: str = "keep"
    expected_version: str = ""
    regions: list[tuple[StrictInt, StrictInt, StrictInt, StrictInt]] | None = Field(None, min_length=1, max_length=20)
    expected_image_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    expected_candidate_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_region_versions(self):
        if self.regions and (not self.expected_image_sha256 or not self.expected_candidate_sha256):
            raise ValueError("局部修复需要原图与候选图 SHA-256，请刷新预览后重试")
        return self


class ImageRegionConflict(ValueError):
    pass


def prepare_regional_candidate(source, candidate, output, payload):
    """Merge normalized and raw source pairs separately, preserving outside pixels."""
    source, candidate, output = Path(source), Path(candidate), Path(output)
    if (sha256_file(source) != payload.expected_image_sha256
            or sha256_file(candidate) != payload.expected_candidate_sha256):
        raise ImageRegionConflict("原图或候选图已变化，请刷新后重新选择修复区域")
    with Image.open(source) as original, Image.open(candidate) as proposed:
        if original.size != proposed.size:
            raise ValueError("候选图与原图画布尺寸不同，不能局部应用")
        width, height = original.size
        for left, top, right, bottom in payload.regions:
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise ValueError("修复区域必须在画布内，且宽高均大于零")
        merged = original.convert("RGB")
        proposed = proposed.convert("RGB")
        for rect in payload.regions:
            merged.paste(proposed.crop(rect), rect)
        merged.save(output, "PNG")
    raw_source, raw_candidate = resolve_mask_source_master(source), resolve_mask_source_master(candidate)
    if raw_source or raw_candidate:
        with Image.open(raw_source or source) as original, Image.open(raw_candidate or candidate) as proposed:
            if original.size != (width, height) or proposed.size != (width, height):
                raise ValueError("原始素材画布不匹配，不能局部应用")
            merged = original.convert("RGB")
            for rect in payload.regions:
                merged.paste(proposed.convert("RGB").crop(rect), rect)
            merged.save(mask_source_raw_path(output), "PNG")
        seal_mask_source_pair(output)
    return output
