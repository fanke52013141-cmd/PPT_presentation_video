"""Transfer client (download/upload) against a real HTTP socket.

用隔离环境 + 随机空闲端口在进程内启动 uvicorn，验证
``agent_client.transfers`` 的有界下载与 multipart 上传走的是真实 HTTP 栈。
不启动第二个面向用户数据的服务实例（conftest 已隔离数据库/runs/data）。
"""

import io
import json
import socket
import threading
import time

import pytest
import urllib.request

from agent_client.client import AgentClient, AgentClientError
from agent_client.transfers import download_file, upload_file


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def live():
    import server

    port = _free_port()
    config = __import__("uvicorn").Config(
        server.app, host="127.0.0.1", port=port, log_level="warning"
    )
    server_instance = __import__("uvicorn").Server(config)
    thread = threading.Thread(target=server_instance.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/api/agent/v1/meta", timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("Isolated Agent server did not start")
    yield {"base_url": base_url, "server": server_instance}
    server_instance.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def project(live):
    detail = json.loads(urllib.request.urlopen(
        live["base_url"] + "/api/agent/v1/capabilities/project.create").read())
    request = urllib.request.Request(
        live["base_url"] + "/api/agent/v1/invoke",
        data=json.dumps({
            "capability_id": "project.create",
            "expected_contract_revision": detail["contract_revision"],
            "arguments": {"name": "传输客户端演练"},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read())
    project_id = body["project"]["project_id"]

    # 上传前置：分镜合约必须存在（两页手动骨架，不经 LLM）
    detail = json.loads(urllib.request.urlopen(
        live["base_url"] + "/api/agent/v1/capabilities/storyboard.skeleton.submit").read())
    request = urllib.request.Request(
        live["base_url"] + "/api/agent/v1/invoke",
        data=json.dumps({
            "capability_id": "storyboard.skeleton.submit",
            "expected_contract_revision": detail["contract_revision"],
            "arguments": {"project_id": project_id, "slides": [
                {"main_title": "第一页", "narration": "第一页的演讲内容。"},
                {"slide_id": "slide_002", "main_title": "第二页", "narration": "第二页的演讲内容。"},
            ]},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        assert json.loads(response.read()).get("success") is True
    return project_id


def test_download_and_upload_roundtrip(live, project, tmp_path):
    client = AgentClient(base_url=live["base_url"])

    # 上传：multipart 传输真实写入服务端
    payload = _png_bytes()
    source = tmp_path / "upload.png"
    source.write_bytes(payload)
    uploaded = upload_file(
        AgentClient(base_url=live["base_url"]),
        f"/api/agent/v1/projects/{project}/images/upload",
        source,
        field="file",
        form_fields={"slide_id": "slide_001", "disposition": "keep"},
        content_type="image/png",
    )
    assert uploaded.get("success") is True, uploaded

    # 下载：受控流式 + 原子落盘（上传图经服务端画布归一化，字节不必等于原图）
    destination = tmp_path / "downloaded.png"
    result = download_file(
        client,
        f"/api/agent/v1/projects/{project}/slides/slide_001/image",
        destination,
    )
    assert result["bytes"] == len(destination.read_bytes())
    assert result["sha256"] == __import__("hashlib").sha256(destination.read_bytes()).hexdigest()
    assert destination.read_bytes()[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10])

    # 哈希不匹配拒绝落盘
    mismatch = tmp_path / "mismatch.png"
    with pytest.raises(AgentClientError) as excinfo:
        download_file(
            client,
            f"/api/agent/v1/projects/{project}/slides/slide_001/image",
            mismatch,
            expected_sha256="0" * 64,
        )
    assert excinfo.value.code == "RESOURCE_HASH_MISMATCH"
    assert not mismatch.exists()

    # 越界路径拒绝
    with pytest.raises(ValueError):
        download_file(client, "https://evil.example/x", tmp_path / "x.bin")
    with pytest.raises(ValueError):
        upload_file(client, "/other/path", source)

    # 超限上传在读取前拒绝
    big = tmp_path / "big.bin"
    big.write_bytes(b"00")
    with pytest.raises(AgentClientError) as small_limit:
        upload_file(
            client,
            f"/api/agent/v1/projects/{project}/images/upload",
            big,
            field="file",
            form_fields={"slide_id": "slide_001"},
            max_bytes=1,
        )
    assert small_limit.value.code == "RESOURCE_TOO_LARGE"


def test_upload_missing_source_and_error_propagation(live, project, tmp_path):
    client = AgentClient(base_url=live["base_url"])
    with pytest.raises(AgentClientError) as missing:
        upload_file(
            client,
            f"/api/agent/v1/projects/{project}/images/upload",
            tmp_path / "no-such.png",
            field="file",
            form_fields={"slide_id": "slide_001"},
        )
    assert missing.value.code == "UPLOAD_SOURCE_MISSING"

    # 服务端校验错误以结构化错误码透传（空 slide_id）
    bad = tmp_path / "bad.png"
    bad.write_bytes(_png_bytes(64, 64))
    with pytest.raises(AgentClientError) as invalid:
        upload_file(
            client,
            f"/api/agent/v1/projects/{project}/images/upload",
            bad,
            field="file",
            form_fields={"slide_id": ""},
        )
    assert invalid.value.status_code == 422


def _png_bytes(width=320, height=180):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 120, 60], fill="#222222")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
