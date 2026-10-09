import json
from pathlib import Path
from types import SimpleNamespace
import image_workflow_service as images


def test_image_list_url_stays_stable_until_image_changes(tmp_path, monkeypatch):
    planning = tmp_path / 'planning'
    planning.mkdir()
    (planning / 'visual_contract.json').write_text(json.dumps({'slides': [{'slide_id': 'slide_001'}]}))
    slide = tmp_path / 'slides' / 'slide_001'
    slide.mkdir(parents=True)
    image = slide / 'visual_draft.png'
    image.write_bytes(b'first-image')
    monkeypatch.setattr(images, 'project_or_404', lambda *_: SimpleNamespace(run_dir=str(tmp_path)))
    monkeypatch.setattr(images, 'visual_provenance_status', lambda *_: {'valid': True})
    monkeypatch.setattr(images, 'step3_image_assignment_version', lambda *_: 'version')
    monkeypatch.setattr(images, 'active_slide_image_generation', lambda *_: [])
    first = images.get_all_images('test', None)['images'][0]['url']
    assert images.get_all_images('test', None)['images'][0]['url'] == first
    image.write_bytes(b'updated-image-longer')
    assert images.get_all_images('test', None)['images'][0]['url'] != first
    image.unlink()
    missing = images.get_all_images('test', None)['images'][0]
    assert missing['exists'] is False and missing['url'] is None
