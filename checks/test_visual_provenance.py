import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_run import (  # noqa: E402
    StageError,
    production_allowed_image_providers,
    validate_image_provenance,
)
from visual_provenance import (  # noqa: E402
    promote_candidate_provenance,
    refresh_provenance_contract_hashes,
    write_visual_provenance,
)


def _contract(run_dir: Path, slide_ids: list[str]) -> Path:
    path = run_dir / "planning" / "visual_contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "visual_contract_v1",
                "slides": [{"slide_id": slide_id} for slide_id in slide_ids],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_generated_provenance_is_verifiable_and_promotable() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        _contract(run_dir, ["slide_001"])
        slide_dir = run_dir / "slides" / "slide_001"
        slide_dir.mkdir(parents=True)
        candidate = slide_dir / "visual_candidate.png"
        candidate.write_bytes(b"candidate-image")
        write_visual_provenance(
            run_dir,
            "slide_001",
            image_path=candidate,
            provider="openai_compatible",
            source_type="api_generation",
            model="gpt-image-1",
            prompt="prompt",
            source_bytes=b"provider-response",
            candidate=True,
        )

        final_image = slide_dir / "visual_draft.png"
        candidate.replace(final_image)
        promoted = promote_candidate_provenance(run_dir, "slide_001")
        assert promoted and promoted["copied_to"].endswith("visual_draft.png")
        validate_image_provenance(slide_dir, {"openai_compatible"})

        final_image.write_bytes(b"tampered-image")
        with pytest.raises(StageError, match="output hash"):
            validate_image_provenance(slide_dir, {"openai_compatible"})


def test_order_only_change_can_refresh_contract_hash_without_fabricating_output() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        contract_path = _contract(run_dir, ["a", "b"])
        for slide_id in ("a", "b"):
            image = run_dir / "slides" / slide_id / "visual_draft.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(slide_id.encode("utf-8"))
            write_visual_provenance(
                run_dir,
                slide_id,
                image_path=image,
                provider="manual_upload",
                source_type="local_upload",
                source_bytes=image.read_bytes(),
            )
        contract_path.write_text(
            json.dumps({"version": "visual_contract_v1", "slides": [{"slide_id": "b"}, {"slide_id": "a"}]}),
            encoding="utf-8",
        )
        assert refresh_provenance_contract_hashes(run_dir, ["b", "a"]) == 2
        for slide_id in ("a", "b"):
            validate_image_provenance(run_dir / "slides" / slide_id, {"manual_upload"})


def test_production_provider_policy_is_configurable() -> None:
    with patch.dict(os.environ, {"PPT_STUDIO_PRODUCTION_IMAGE_PROVIDERS": "codex_image_gen,manual_upload"}):
        assert production_allowed_image_providers() == ("codex_image_gen", "manual_upload")

    source = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "write_visual_provenance(" in source
    assert "project_generate_prompt_for_slide(" in source
