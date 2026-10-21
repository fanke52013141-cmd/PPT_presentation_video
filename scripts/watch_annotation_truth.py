"""Bounded collector for completed acceptance TTS staging snapshots.

Read-only against live artifacts; all writes remain in the acceptance bundle.
Human truth is never generated. Prediction output stays outside the served folder.
"""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUN = ROOT / 'outputs/annotation-bcd/isolated/runs/annotation_truth_100'
OUT = ROOT / 'outputs/annotation-bcd/human-truth'
PUBLIC = OUT / 'public'
JOB = '908a573dcd9d431aa22b2d6627251a32'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def publish(rows):
    public = []
    for row in rows:
        public.append({k: row.get(k) for k in ('sample_id', 'category', 'text', 'quote', 'range', 'audio_sha256')})
        public[-1]['audio_url'] = 'audio/'+row['sample_id']+'.mp3' if row.get('audio_sha256') else None
    html = (ROOT/'scripts/annotation_truth_review.html').read_text(encoding='utf-8')
    write(PUBLIC/'index.html', html.replace('__SAMPLES__', json.dumps(public, ensure_ascii=False).replace('<', '\\u003c')))
    write(OUT/'predictions.json', rows)
    write(PUBLIC/'status.json', {'total': len(rows), 'audio_ready': sum(bool(r.get('audio_sha256')) for r in rows),
                                'labelled': 0, 'predictions_public': False})


def main():
    rows = json.loads((RUN/'acceptance_mapping.json').read_text(encoding='utf-8'))
    PUBLIC.mkdir(parents=True, exist_ok=True)
    known = {row['slide_id']: row for row in rows}
    publish(rows)
    deadline = time.monotonic()+7200
    previous = -1
    while time.monotonic() < deadline:
        sources = list(RUN.glob('slides/*')) + list(Path(tempfile.gettempdir()).glob('tts-stage-*'))
        for directory in sources:
            try:
                timeline = json.loads((directory/'audio_timeline.json').read_text(encoding='utf-8'))
                sid = timeline.get('slide_id')
                if sid not in known:
                    continue
                row = known[sid]
                if row.get('audio_sha256'):
                    continue
                text = (directory/'tts_text.txt').read_text(encoding='utf-8').strip()
                if text != row['text'] or not (directory/'tts_metadata.json').is_file():
                    continue
                data = (directory/'voice.mp3').read_bytes()
                if not data:
                    continue
                target = PUBLIC/'audio'/f"{row['sample_id']}.mp3"
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(data)
                row['audio_sha256'] = hashlib.sha256(data).hexdigest()
                row['duration_sec'] = timeline.get('audio_content_duration_sec') or timeline.get('duration_sec')
                row['audio_snapshot_source'] = 'complete_provider_staging' if directory.name.startswith('tts-stage-') else 'published'
            except (OSError, ValueError, KeyError):
                continue
        count = sum(bool(r.get('audio_sha256')) for r in rows)
        if count != previous:
            publish(rows)
            print(json.dumps({'audio_ready': count, 'total': len(rows), 'human_labels': 0}), flush=True)
            previous = count
        if count == len(rows):
            break
        time.sleep(15)
    else:
        write(OUT/'collector_error.json', {'reason': 'timeout', 'audio_ready': previous})
        return 1
    from annotation_alignment_worker import run_alignment
    from annotation_alignment import resolve_anchor_times
    from types import SimpleNamespace
    for index, row in enumerate(rows):
        directory = OUT/'alignment'/row['sample_id']
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PUBLIC/'audio'/f"{row['sample_id']}.mp3", directory/'voice.mp3')
        beats = [{'beat_id': 'b1', 'spoken_text': row['text']}]
        write(directory/'narration_beats.json', {'beats': beats})
        result = run_alignment(directory, beats, threading.Event())
        write(directory/'word_alignment.json', result)
        anchor = SimpleNamespace(beat_id='b1',range_start=row['range'][0],range_end=row['range'][1],quote=row['quote'])
        resolved = resolve_anchor_times([SimpleNamespace(annotation_id=row['sample_id'],anchor=anchor)],result)
        prediction = resolved.get(row['sample_id'])
        row['reliable'] = bool(prediction)
        row['predicted_start_sec'] = prediction['start'] if prediction else None
        write(OUT/'predictions.json', rows)
        print(json.dumps({'aligned': index+1, 'total': len(rows)}), flush=True)
    write(OUT/'collection_complete.json', {'audio_ready': len(rows), 'predictions_complete': True,
          'unique_audio_hashes': len({r['audio_sha256'] for r in rows}), 'human_labels': 0})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
