from pathlib import Path
from types import SimpleNamespace
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from account_context import account_scope  # noqa: E402
import project_style_template_service as service  # noqa: E402
from global_image_style_service import build_image_style_prompt  # noqa: E402


class DummyHttpException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _save_image(data: bytes, target: str) -> None:
    from io import BytesIO

    image = Image.open(BytesIO(data)).convert("RGB")
    image.save(target, "PNG")


def _portable_context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        image_class=Image,
        process_and_save_image=_save_image,
        http_exception=DummyHttpException,
    )


def test_style_template_library_is_isolated_by_account(tmp_path: Path) -> None:
    context = SimpleNamespace(data_dir=tmp_path)
    default_root = service.templates_root(context)
    with account_scope("account-a"):
        account_a_root = service.templates_root(context)
        service.write_templates(context, [{"id": "aaaaaaaaaaaa", "name": "A"}])
        assert service.read_templates(context)[0]["name"] == "A"
    with account_scope("account-b"):
        account_b_root = service.templates_root(context)
        assert service.read_templates(context) == []

    assert default_root != account_a_root
    assert account_a_root != account_b_root
    assert "accounts" in account_a_root.parts


def test_builtin_teaching_styles_have_locked_prompts_and_references() -> None:
    context = SimpleNamespace(
        repo_root=ROOT,
        data_dir=ROOT / "data",
        build_image_style_prompt=build_image_style_prompt,
        http_exception=DummyHttpException,
    )
    summaries = service.builtin_template_summaries(context)
    assert len(summaries) == 7
    assert {item["id"] for item in summaries} == set(service.BUILTIN_IMAGE_STYLE_TEMPLATES)
    for item in summaries:
        detail = service.template_detail(context, item["id"])
        assert item["built_in"] is True
        assert item["locked"] is True
        assert detail["style"]["system_content"]
        assert detail["style"]["production_contract_version"] == "step3_visual_contract_v3"
        assert detail["references"]["images"]


def test_portable_style_round_trip_keeps_prompt_and_reference_images(tmp_path: Path) -> None:
    context = _portable_context(tmp_path)
    template_id = "aaaaaaaaaaaa"
    with account_scope("account-a"):
        source = service.templates_root(context) / template_id
        references = source / "references"
        references.mkdir(parents=True)
        service._write_json(source / "style.json", {
            "style_name": "品牌手绘",
            "system_content": "保持蓝紫色线稿和统一留白。",
        })
        image_path = references / "style_reference_01.png"
        Image.new("RGB", (16, 16), "#7367f0").save(image_path, "PNG")
        service._write_json(source / "references.json", {
            "version": "step3_style_references_v1",
            "style_name": "品牌手绘",
            "images": [{
                "index": 1,
                "filename": image_path.name,
                "source": "upload",
            }],
        })
        service.write_templates(context, [{
            "id": template_id,
            "name": "品牌手绘",
            "version": 1,
            "content_hash": "hash-a",
            "reference_count": 1,
        }])
        bundle = service.export_portable_templates(context)

    assert bundle["templates"][0]["references"]["images"][0]["data"]

    with account_scope("account-b"):
        service.validate_portable_templates(context, bundle)
        service.import_portable_templates(context, bundle)
        detail = service.template_detail(context, template_id)

    assert detail["style"]["system_content"] == "保持蓝紫色线稿和统一留白。"
    assert detail["template"]["account_id"] == "account-b"
    assert detail["template"]["reference_count"] == 1
    assert len(detail["references"]["images"]) == 1
