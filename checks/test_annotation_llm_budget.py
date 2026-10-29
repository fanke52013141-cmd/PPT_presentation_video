from types import SimpleNamespace
import pytest
import json_llm_service as service

@pytest.mark.parametrize("fails", [False, True])
def test_scoped_budget_and_client_cleanup(monkeypatch, tmp_path, fails):
    calls = []
    closed = []
    def create(**kwargs):
        calls.append(kwargs)
        if fails:
            raise TimeoutError("timed out")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"suggestions":[]}'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: closed.append(True))
    from contextlib import nullcontext
    monkeypatch.setattr(service, "get_setting", lambda key, default=None: {"llm_api_key":"test", "llm_model":"test", "llm_max_tokens":"64000"}.get(key,default))
    def factory(**kwargs):
        assert kwargs["timeout"] == 180
        return client
    monkeypatch.setattr(service, "get_openai_client", factory)
    monkeypatch.setattr(service, "governed_llm_request", lambda *_a: nullcontext())
    arguments = dict(system_prompt="system",user_prompt="input",run_dir=str(tmp_path),artifact_prefix="annotation",schema_hint="{}",request_timeout=180,max_tokens_limit=4096)
    if fails:
        with pytest.raises(service.HTTPException): service.generate_json_with_configured_llm(**arguments)
    else:
        assert service.generate_json_with_configured_llm(**arguments) == {"suggestions":[]}
    assert calls[0]["max_tokens"] == 4096
    assert closed == [True]


@pytest.mark.parametrize("model,endpoint,enabled,expected", [
    ("doubao-seed-2-1-turbo", "https://example.test/v1", True, True),
    ("other", "https://ark.cn-beijing.volces.com/api/v3", True, True),
    ("other", "https://example.test/v1", True, False),
    ("doubao-seed-2-1-turbo", "https://example.test/v1", False, False),
])
def test_bound_provider_options_survive_json_repair(monkeypatch, tmp_path, model, endpoint, enabled, expected):
    from contextlib import nullcontext

    calls, governed, closed = [], [], []
    def create(**kwargs):
        calls.append(kwargs)
        content = "broken JSON" if len(calls) == 1 else '{"suggestions":[]}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: closed.append(True))
    monkeypatch.setattr(service, "get_openai_client", lambda **_: client)
    monkeypatch.setattr(service, "get_setting", lambda _key, default=None: default)
    def governor(url):
        governed.append(url)
        return nullcontext()
    monkeypatch.setattr(service, "governed_llm_request", governor)
    result = service.generate_json_with_configured_llm(
        system_prompt="system", user_prompt="input", run_dir=str(tmp_path),
        artifact_prefix="annotation", schema_hint="{}", disable_thinking=enabled,
        model_binding=SimpleNamespace(api_key="test", model=model, endpoint=endpoint),
    )
    assert result == {"suggestions": []}
    assert len(calls) == 2 and governed == [endpoint, endpoint]
    for call in calls:
        assert ("extra_body" in call) is expected
        if expected:
            assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert closed == [True]
