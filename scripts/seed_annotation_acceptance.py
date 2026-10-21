"""Seed disposable acceptance projects, never the production database.

Requires the already running isolated acceptance server on port 8015.
Copies only TTS settings into its separate DB; never prints credential values.
"""
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'outputs' / 'annotation-bcd' / 'isolated'
os.environ['PPT_STUDIO_DB_PATH'] = str(OUT / 'projects.db')
os.environ['PPT_STUDIO_RUNS_DIR'] = str(OUT / 'runs')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    from database import SessionLocal, Project
    from canvas_profile_service import write_project_canvas_snapshot
    from visual_provenance import write_visual_provenance
    from PIL import Image, ImageDraw, ImageFont
    # The fixed destination is isolated and must never resolve to the real DB.
    assert (OUT / 'projects.db').resolve() != (ROOT / 'data/projects.db').resolve()
    with sqlite3.connect(ROOT / 'data/projects.db') as source:
        settings = source.execute("select key,value from settings where key like 'tts_%'").fetchall()
    with sqlite3.connect(OUT / 'projects.db') as target:
        for key, value in settings:
            target.execute('insert into settings(key,value) values (?,?) on conflict(key) do update set value=excluded.value', (key, value))
    samples = json.loads((ROOT / 'checks/fixtures/annotations/alignment_acceptance_100.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT / 'outputs/annotation-bcd/real-cases/summary.json').read_text(encoding='utf-8'))
    specs = [('annotation_truth_100', samples, False),
             ('annotation_cases_landscape', [c for c in cases if c['kind'] != 'portrait'], False),
             ('annotation_cases_portrait', [c for c in cases if c['kind'] == 'portrait'], True)]
    for pid, rows, portrait in specs:
        run = OUT / 'runs' / pid
        if (run / 'planning/visual_contract.json').exists():
            print(pid, 'already seeded', flush=True)
            continue
        size = (1080, 1920) if portrait else (1920, 1080)
        slides, manifest, mapping = [], [], []
        for i, row in enumerate(rows):
            sid = f'slide_{i+1:03}'
            directory = run / 'slides' / sid
            directory.mkdir(parents=True, exist_ok=True)
            if pid == 'annotation_truth_100':
                spoken = row['text']
                image = Image.new('RGB', size, 'white')
                ImageDraw.Draw(image).text((100, 200), row['quote'], font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 64), fill='black')
                image.save(directory / 'visual_draft.png')
                items = []
            else:
                phrase = ['完整轨迹', '关键结论'][row['case'] % 2]
                spoken = f'先提到{phrase}。现在重点讲到{phrase}。' if row['kind'] == 'repeat' else f'重点是{phrase}，请观察对应内容。'
                shutil.copy2(ROOT / f"outputs/annotation-bcd/real-cases/case_{row['case']:02}.png", directory / 'visual_draft.png')
                layout = json.loads((ROOT / f"outputs/annotation-bcd/real-cases/layout_{row['case']:02}.json").read_text(encoding='utf-8'))
                layout['slide_id'] = sid
                write(directory / 'text_layout.json', layout)
                items = row['items']
                if row['kind'] == 'protected':
                    # Retain a genuinely manual locked item in the downstream test.
                    item = json.loads(json.dumps(cases[row['case'] % 2]['items'][0]))
                    start = spoken.index(phrase)
                    item['anchor'].update(beat_id='b1', range=[start, start+len(phrase)], quote=phrase)
                    item['target']['polygons'] = [[[100, 190], [380, 190], [380, 290], [100, 290]]]
                    item['target'].update(kind='region', token_ids=[], layout_revision=None, granularity='region', quote=None)
                    item['protection'].update(source='manual', locked=True)
                    item['status']['content'] = 'draft'
                    items = [item]
                for j, item in enumerate(items):
                    item['annotation_id'] = f'ann_{j+1:03}'
                    item['target']['layout_revision'] = 1 if item['target']['kind'] == 'text' else None
                write(directory / 'annotations.json', {'schema_version': 1, 'slide_id': sid, 'revision': 1, 'items': items})
            beats = [{'id': 'b1', 'beat_id': 'b1', 'spoken_text': spoken}]
            write(directory / 'narration_beats.json', {'beats': beats})
            (directory / 'tts_text.txt').write_text(spoken, encoding='utf-8')
            slides.append({'slide_id': sid, 'title': row.get('category', row.get('kind')), 'narration': spoken, 'narration_beats': beats})
            manifest.append({'slide_id': sid, 'slide_dir': str(directory), 'master': str(directory / 'visual_draft.png'), 'groups': []})
            mapping.append({'slide_id': sid, **row})
        write(run / 'planning/visual_contract.json', {'schema_version': 3, 'slides': slides})
        write(run / 'planning/narration_beats.json', {'slides': [{'slide_id': x['slide_id'], 'beats': x['narration_beats']} for x in slides]})
        write(run / 'reveal_manifest.json', {'version': 'reveal_v1', 'canvas': {'width': size[0], 'height': size[1], 'background': '#FEFDF9'}, 'slides': manifest})
        write(run / 'planning/annotation_settings.json', {'schema_version': 1, 'revision': 1, 'enabled': pid != 'annotation_truth_100'})
        write(run / 'acceptance_mapping.json', mapping)
        (run / 'inputs').mkdir(exist_ok=True)
        (run / 'inputs/article.md').write_text('\n\n'.join(x['narration'] for x in slides), encoding='utf-8')
        project = Project(id=pid, name=pid+'-隔离验收', run_dir=str(run), account_id='default', current_step=7,
                          canvas_profile='portrait_9_16' if portrait else 'landscape_16_9',
                          presentation_mode='full_frame', mask_enabled=0,
                          step_status=json.dumps({str(i): 'completed' for i in range(1, 7)}))
        with SessionLocal() as db:
            db.add(project)
            db.commit()
            write_project_canvas_snapshot(project)
        for slide in manifest:
            write_visual_provenance(run, slide['slide_id'], image_path=slide['master'], provider='manual_upload', source_type='manual_upload')
        import subprocess
        subprocess.run([sys.executable, str(ROOT/'scripts/build_reveal_scene.py'), '--manifest', str(run/'reveal_manifest.json')], check=True)
        print(pid, len(rows), 'seeded', flush=True)


if __name__ == '__main__':
    main()
