# Code review round 2

Date: 2026-06-21

## Focus

- Remotion TypeScript validation.
- TTS helper CLI health.
- Documentation command consistency.

## Findings

- Running `npx tsc --noEmit -p scripts\remotion\tsconfig.json` from the repo root did not find the Remotion subproject TypeScript dependency.
- Correct command is to run inside `scripts/remotion` after `npm install`.
- README and AGENTS were updated to reflect that.

## Commands

```powershell
Push-Location scripts\remotion
npm install
npx tsc --noEmit -p tsconfig.json
Pop-Location
python scripts\generic_tts.py --help
```

## Result

Passed with the corrected working directory.
