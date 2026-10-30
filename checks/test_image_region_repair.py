import pytest
from PIL import Image

from artifact_fingerprint import sha256_file
from image_region_repair import ImageCandidateApplyPayload, ImageRegionConflict, prepare_regional_candidate
from ai_mask_contracts import mask_source_raw_path, resolve_mask_source_master, seal_mask_source_pair


def setup_images(tmp_path):
    source, candidate = tmp_path / "visual_draft.png", tmp_path / "visual_candidate.png"
    Image.new("RGB", (100, 80), "white").save(source)
    Image.new("RGB", (100, 80), "blue").save(candidate)
    payload = ImageCandidateApplyPayload(slide_id="slide_001", regions=[(20, 10, 40, 30)],
        expected_image_sha256=sha256_file(source), expected_candidate_sha256=sha256_file(candidate))
    return source, candidate, payload


def test_region_application_preserves_every_outside_pixel_and_raw_pair(tmp_path):
    source, candidate, payload = setup_images(tmp_path)
    Image.new("RGB", (100, 80), "#F7F7F7").save(mask_source_raw_path(source))
    seal_mask_source_pair(source)
    output = tmp_path / "merged.png"
    prepare_regional_candidate(source, candidate, output, payload)
    image, raw = Image.open(output), Image.open(resolve_mask_source_master(output))
    for y in range(80):
        for x in range(100):
            inside = 20 <= x < 40 and 10 <= y < 30
            assert image.getpixel((x, y)) == ((0, 0, 255) if inside else (255, 255, 255))
            assert raw.getpixel((x, y)) == ((0, 0, 255) if inside else (247, 247, 247))


def test_stale_region_repair_does_not_change_either_input(tmp_path):
    source, candidate, payload = setup_images(tmp_path)
    payload.expected_image_sha256 = "stale"
    before = {p: p.read_bytes() for p in (source, candidate)}
    with pytest.raises(ImageRegionConflict):
        prepare_regional_candidate(source, candidate, tmp_path / "merged.png", payload)
    assert {p: p.read_bytes() for p in before} == before
    assert not (tmp_path / "merged.png").exists()


@pytest.mark.parametrize("region", [(-1, 0, 10, 10), (0, 0, 101, 10), (20, 10, 20, 30)])
def test_invalid_region_rejected_before_writing(tmp_path, region):
    source, candidate, payload = setup_images(tmp_path)
    payload.regions = [region]
    with pytest.raises(ValueError):
        prepare_regional_candidate(source, candidate, tmp_path / "merged.png", payload)
    assert not (tmp_path / "merged.png").exists()
