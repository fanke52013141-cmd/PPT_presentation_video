from creation_config_defaults import default_creation_config_payload


def test_new_creation_config_payload_contains_canonical_prompts() -> None:
    payload = default_creation_config_payload()
    prompts = payload["prompts"]

    assert payload["schema_version"] == "creation_config_v1"
    assert set(prompts) == {
        "article_generation",
        "storyboard",
        "visualization",
        "image_generation",
        "ai_mask",
        "narration_annotation",
    }
    assert prompts["article_generation"]["system_content"]
    assert prompts["storyboard"]["system_content"]
    assert prompts["storyboard"]["output_example"]
    assert prompts["visualization"]["system_content"]
    assert prompts["image_generation"]["system_content"]
    assert prompts["ai_mask"]["system_content"]
    assert prompts["narration_annotation"]["system_content"]
    assert prompts["narration_annotation"]["output_example"]
    assert payload["model_bindings"] == {}


def test_new_creation_config_payload_is_fresh_and_editable() -> None:
    first = default_creation_config_payload()
    second = default_creation_config_payload()
    first["prompts"]["article_generation"]["system_content"] = "changed"

    assert second["prompts"]["article_generation"]["system_content"] != "changed"
