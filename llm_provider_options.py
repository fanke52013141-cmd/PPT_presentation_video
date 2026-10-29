"""Pure provider options shared by bounded structured-output tasks."""


def non_thinking_vendor_options(model: str, base_url: str | None) -> dict:
    model_name = str(model or "").strip().lower()
    endpoint = str(base_url or "").strip().lower()
    if model_name.startswith("doubao-") or "volces.com" in endpoint:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}
