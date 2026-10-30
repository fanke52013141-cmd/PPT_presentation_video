"""Generate repair candidates in batches, then explicitly apply reviewed regions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_client.client import AgentClient
from image_region_repair import ImageCandidateApplyPayload
from pipeline_lifecycle import write_json_atomic


def run_batch(client, manifest, report_path, *, apply_reviewed=False):
    project, batch = manifest["project_id"], manifest["batch_id"]
    entries = manifest["slides"]
    if not project or not batch or not entries or len(entries) > 100:
        raise ValueError("Require project_id, batch_id and 1–100 slides")
    ids = [entry["slide_id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate slide_id")
    if apply_reviewed:
        entries = [entry for entry in entries if entry.get("reviewed") is True]
        for entry in entries:
            ImageCandidateApplyPayload.model_validate(entry)
            if not entry.get("regions"):
                raise ValueError("Reviewed repair application requires explicit regions")
    elif any(not str(entry.get("prompt") or "").strip() for entry in entries):
        raise ValueError("Each candidate needs an explicit, complete image prompt")
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"operations": {}}
    context = hashlib.sha256((client.base_url + "\0" + (client.app_token or "")).encode()).hexdigest()
    if report.get("client_context", context) != context:
        raise ValueError("Report belongs to a different server or authentication context")
    report["client_context"] = context
    mode = "apply" if apply_reviewed else "generate"
    capability = "image.candidate.apply" if apply_reviewed else "image.generate"
    for entry in entries:
        identity = json.dumps({"project": project, "batch": batch, "mode": mode, "entry": entry}, sort_keys=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        scope = [project, batch, mode, entry["slide_id"]]
        if any(value.get("scope") == scope and key != digest for key, value in report["operations"].items()):
            raise ValueError("Batch parameters changed; inspect prior results before explicitly choosing a new batch_id")
        slot = report["operations"].get(digest)
        if slot and slot["status"] == "succeeded":
            continue
        if slot and slot["status"] == "failed":
            raise ValueError("Prior request failed; inspect it before starting a new batch")
        if slot is None:
            slot = {"scope": scope, "slide_id": entry["slide_id"], "status": "pending", "key": "repair-" + digest,
                    "contract_revision": client.describe(capability)["contract_revision"]}
            report["operations"][digest] = slot
        slot["status"] = "unknown_result"
        write_json_atomic(report_path, report)
        arguments = {"project_id": project}
        if apply_reviewed:
            arguments["payload"] = ImageCandidateApplyPayload.model_validate(entry).model_dump(exclude_none=True)
        else:
            arguments.update(slide_id=entry["slide_id"], prompt=entry["prompt"], preview=True, idempotency_key=slot["key"])
        # Candidate application is not idempotent: a lost response must be inspected,
        # never retried automatically. Generation reuses its exact key and revision.
        if apply_reviewed and slot.get("submitted"):
            raise ValueError("Unknown application result; inspect current image before continuing")
        slot["submitted"] = True
        write_json_atomic(report_path, report)
        try:
            slot["result"] = client.invoke(capability, arguments, expected_contract_revision=slot["contract_revision"])
        except Exception as exc:
            if getattr(exc, "status_code", 0):
                slot["status"] = "failed"
            slot["error_type"] = type(exc).__name__
            write_json_atomic(report_path, report)
            raise
        if not apply_reviewed and slot["result"].get("candidate_sha256") and slot["result"].get("image_sha256"):
            review = report.setdefault("review_manifest", {"project_id": project, "batch_id": batch, "slides": []})
            review["slides"].append({"slide_id": entry["slide_id"], "reviewed": False,
                "regions": entry.get("regions") or [], "disposition": entry.get("disposition", "keep"),
                "expected_image_sha256": slot["result"]["image_sha256"],
                "expected_candidate_sha256": slot["result"]["candidate_sha256"]})
        slot["status"] = "succeeded"
        write_json_atomic(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--apply-reviewed", action="store_true")
    parser.add_argument("--review-manifest", type=Path)
    args = parser.parse_args()
    report = run_batch(AgentClient(base_url=args.base_url, timeout=900),
              json.loads(args.manifest.read_text(encoding="utf-8")), args.report, apply_reviewed=args.apply_reviewed)
    if args.review_manifest and not args.apply_reviewed:
        write_json_atomic(args.review_manifest, report.get("review_manifest", {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
