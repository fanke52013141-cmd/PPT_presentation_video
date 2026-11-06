"""Verify both presenter modes through the isolated running application's HTTP API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.media_tools import probe_media_duration_sec, probe_video_metadata, resolve_media_tool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    media = args.media_root.resolve()
    # Do not run against a production instance: fixture projects must be present.
    expected = json.loads((media / "acceptance_projects.json").read_text(encoding="utf-8"))
    projects = {item["id"].split("_")[-1]: item for item in expected}
    marker = media / "http_verification.json"
    record = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
    def save():
        marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    with httpx.Client(base_url=args.url, trust_env=False, timeout=120,
                      headers={"X-PPT-Studio-Request": "1"}) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        for item in expected:
            result = request("GET", "/api/projects/" + item["id"]).json()
            if result.get("id") != item["id"]:
                raise ValueError("Isolated fixture project is missing")
        upload_prefix = "/api/projects/" + projects["upload"]["id"] + "/digital-human"
        before = request("GET", upload_prefix + "/health").json()["job_count"]
        with (media / "reference.mp4").open("rb") as stream:
            request("POST", upload_prefix + "/upload", files={"file": ("reference.mp4", stream, "video/mp4")})
        downloaded = request("GET", upload_prefix + "/upload/video").content
        assert hashlib.sha256(downloaded).digest() == hashlib.sha256((media / "reference.mp4").read_bytes()).digest()
        assert request("GET", upload_prefix + "/health").json()["job_count"] == before
        record["direct_upload"] = {"verified": True, "model_jobs_launched": 0}
        save()

        prefix = "/api/projects/" + projects["motion"]["id"] + "/digital-human"
        if not record.get("motion_job_id"):
            with (media.parent / "lecturer_b_20261105.png").open("rb") as stream:
                avatar = request("POST", prefix + "/avatars", files={"file": ("lecturer.png", stream, "image/png")}).json()
            request("PUT", prefix + "/config", json={"enabled": True, "mode": "portrait",
                    "avatar_id": avatar["avatar_id"], "motion_source": "custom"})
            for expected_change in (True, False):
                with (media / "reference.mp4").open("rb") as stream:
                    upload_result = request("POST", prefix + "/motion", files={"file": ("driving.mp4", stream, "video/mp4")}).json()
                assert upload_result["changed"] is expected_change
            result = request("POST", prefix + "/generate-full", json={}).json()
            record["motion_job_id"] = result["job_id"]
            save()
            print("Submitted exact application job: " + result["job_id"], flush=True)
        job_id = record["motion_job_id"]
        previous = None
        deadline = time.monotonic() + 7200
        while time.monotonic() < deadline:
            job = request("GET", prefix + "/jobs/" + job_id).json()["job"]
            if job.get("stale"):
                raise ValueError("Application job inputs changed; original job cannot be published")
            status = job.get("status")
            if status != previous:
                print("Application job: " + str(status), flush=True)
                previous = status
            if status == "failed":
                raise RuntimeError(job.get("error"))
            if status == "done" and job.get("video_exists"):
                break
            time.sleep(2)
        else:
            raise TimeoutError("Original job still pending; rerun checks this same ID")
        config = request("GET", prefix + "/config").json()
        assert config["slides"]["full"]["video_exists"] and not config["slides"]["full"]["video_stale"]
        application_video = media / "application_transferred_b.mp4"
        application_video.write_bytes(request("GET", prefix + "/slides/full/video").content)
        record["motion_generation"] = probe_video_metadata(application_video)
        assert record["motion_generation"]["duration_sec"] >= 20
        save()

        # Approved bitmap body + real course narration; no PPT body is redrawn.
        image = Path(__file__).resolve().parents[1] / "references/style_reference/PPT示例.png"
        ffmpeg = resolve_media_tool("ffmpeg")
        for mode, item in projects.items():
            run = Path(item["run_dir"])
            lesson = run / "presenter_verification_lesson.mp4"
            narration = run / "slides/slide_001/voice.mp3"
            duration = probe_media_duration_sec(narration)
            if not duration:
                raise ValueError("Could not read fixture narration duration")
            if abs((probe_media_duration_sec(lesson) or 0) - duration) > 0.1:
                subprocess.run([ffmpeg, "-v", "error", "-y", "-loop", "1", "-i", str(image),
                    "-i", str(run / "slides/slide_001/voice.mp3"), "-vf",
                    "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xFEFDF9",
                    "-r", "25", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-t", str(duration), str(lesson)], check=True)
            route = "/api/projects/" + item["id"] + "/digital-human"
            composed = request("POST", route + "/composite/full", json={"base_video": lesson.name}).json()
            output = media / ("mode_" + mode + "_composite.mp4")
            output.write_bytes(request("GET", composed["output_url"]).content)
            metadata = probe_video_metadata(output)
            assert metadata and metadata["duration_sec"] >= 20
            record[mode + "_composite"] = {**metadata, "path": str(output)}
            save()
        print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
