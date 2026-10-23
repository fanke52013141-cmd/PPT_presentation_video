"""Registered artifacts retain exact identity and validated file ownership."""

import hashlib
import json
from pathlib import Path
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent_contract.artifacts import build_resource_uri
from mcp_server.resources import parse_resource_uri, read_resource


@pytest.fixture(scope="module")
def api():
    import server
    return TestClient(server.app, client=("artifact-identity-" + uuid.uuid4().hex, 50000))


@pytest.fixture
def registered(api):
    from database import Project, SessionLocal
    from artifact_registry import record_artifact

    response = api.post("/api/agent/v1/projects", json={"name": "Artifact exact identity"})
    assert response.status_code == 200, response.text
    pid = response.json()["project"]["project_id"]
    artifacts = []
    with SessionLocal() as db:
        project = db.get(Project, pid)
        run_dir = Path(project.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        for index in range(2):
            path = run_dir / f"output-{index}.mp4"
            path.write_bytes(f"video-{index}".encode())
            rec = record_artifact(db, project_id=pid, artifact_type="video", path=path,
                                  relative_path=path.name, mime_type="video/mp4")
            artifacts.append(rec.id)
        db.commit()
    return pid, artifacts, run_dir


def test_metadata_and_download_keep_the_exact_artifact(api, registered):
    pid, artifacts, run_dir = registered
    listing = api.get(f"/api/agent/v1/projects/{pid}/artifacts").json()["artifacts"]
    assert {item["resource_uri"] for item in listing} == {
        build_resource_uri(pid, "video", artifact_id=identity) for identity in artifacts
    }
    for index, identity in enumerate(artifacts):
        metadata = api.get(f"/api/agent/v1/projects/{pid}/artifacts/{identity}").json()
        content = f"video-{index}".encode()
        assert metadata["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
        assert api.get(metadata["download_url"]).content == content
        uri = metadata["artifact"]["resource_uri"]
        assert parse_resource_uri(uri) == (pid, "artifact", {"project_id": pid, "artifact_id": identity})
        client = MagicMock()
        client.get_artifact.return_value = metadata
        resource = read_resource(uri, client)
        assert json.loads(resource["contents"][0]["text"]) == metadata
        client.get_artifact.assert_called_once_with(pid, identity)
        client.get_bytes.assert_not_called()


def test_artifact_file_escape_is_never_hashed_or_downloaded(api, registered):
    from database import ArtifactRecord, SessionLocal
    pid, artifacts, run_dir = registered
    outside = run_dir.parent / ("outside-" + uuid.uuid4().hex)
    outside.write_bytes(b"private-neighbor")
    with SessionLocal() as db:
        db.get(ArtifactRecord, artifacts[0]).relative_path = "../" + outside.name
        db.commit()
    metadata = api.get(f"/api/agent/v1/projects/{pid}/artifacts/{artifacts[0]}")
    assert metadata.status_code == 200
    assert metadata.json()["artifact"]["sha256"] is None
    assert api.get(metadata.json()["download_url"]).status_code == 404


def test_slide_files_with_the_same_name_keep_independent_registry_ids(api, registered):
    from database import ArtifactRecord, SessionLocal
    from artifact_registry import record_artifact, remove_artifact_record

    pid, _, run_dir = registered
    identities = []
    with SessionLocal() as db:
        for slide in ("slide_1", "slide_2"):
            path = run_dir / "slides" / slide / "visual_draft.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(slide.encode())
            rec = record_artifact(db, project_id=pid, artifact_type="image", path=path,
                                  relative_path=f"slides/{slide}/visual_draft.png", mime_type="image/png",
                                  metadata={"slide_id": slide})
            identities.append(rec.id)
        db.commit()
        assert identities[0] != identities[1]
        repeat = record_artifact(db, project_id=pid, artifact_type="image",
                                 path=run_dir / "slides/slide_2/visual_draft.png",
                                 relative_path="slides/slide_2/visual_draft.png", mime_type="image/png")
        assert repeat.id == identities[1]
        removed = remove_artifact_record(db, project_id=pid, artifact_type="image", filename="visual_draft.png",
                                         relative_path="slides/slide_1/visual_draft.png")
        db.commit()
        assert removed == 1
        assert db.get(ArtifactRecord, identities[1]) is not None
    metadata = api.get(f"/api/agent/v1/projects/{pid}/artifacts/{identities[1]}").json()
    assert api.get(metadata["download_url"]).content == b"slide_2"


@pytest.mark.parametrize("uri", ["ppt://projects/p/artifacts/..", "ppt://projects/p/artifacts/%2fsecret", "ppt://projects/p%3fother/artifacts/a"])
def test_mcp_resource_rejects_ambiguous_identifiers(uri):
    assert parse_resource_uri(uri) is None
