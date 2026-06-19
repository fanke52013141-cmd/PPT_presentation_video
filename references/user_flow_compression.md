# User Flow Compression

The web interface exposes six user-facing stages while preserving internal
backend step IDs `1..8`.

## Visible workflow

| Visible stage | Internal state | Completion rule |
| --- | --- | --- |
| Import article | 1 | Step 1 completed |
| Storyboard planning | 2 | Step 2 completed |
| Image generation | 3 + 4 | Image confirmation (Step 4) completed |
| Mask annotation | 5 | Step 5 completed |
| Narration and audio | 6 + 7 | Steps 6 and 7 completed and audio explicitly confirmed |
| Video rendering | 8 | Step 8 completed |

## Compatibility mapping

- Internal Step 4 opens visible Step 5 (Mask annotation).
- Internal Step 7 opens visible Step 6 (Narration and audio).
- A confirmed Step 7 opens visible Step 8 on the next project entry.
- Existing projects with Step 7 completed but no confirmation marker return to
  the audio review area once so the user can explicitly confirm the audio.

## Audio confirmation

Audio generation and audio confirmation are different states:

- Successful synthesis marks internal Step 7 as `in_progress`.
- Confirmation writes `planning/audio_confirmed.json` and marks Step 7
  `completed`.
- Editing any upstream step clears the confirmation marker.
- Video rendering is rejected by the backend until the marker exists.

This marker is stored in the run directory, so no database migration is needed.

## Frontend source of truth

`static/flow.js` owns visible labels, numbering, progress calculation, legacy
step mapping, and unlock rules. UI code should not duplicate those rules.

Run its checks with:

```powershell
node checks/test_visible_flow.js
python checks/test_audio_confirmation.py
```
