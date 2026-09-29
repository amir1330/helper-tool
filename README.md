# Pipipupu — clipboard assistant + OCR

Triple-click anywhere to OCR the screen (English + Russian) and copy text to clipboard.
A small floating window (`pipi pupu`) sends clipboard text to an LLM and shows the short answer.

## Files

| File | Purpose |
|---|---|
| `pipipupu.py` | The app (only script) |
| `config.json` | Your local config + API keys (gitignored, never commit) |
| `config.example.json` | Safe template to copy from |
| `tesseract/` | Bundled Tesseract runtime (`tesseract.exe` + DLLs + `tessdata/eng+rus`) |
| `pipipupu.spec` | PyInstaller build definition |
| `requirements.txt` | Windows Python deps |

Removed: `tool2.py` (old prototype), Tesseract training tools (`*training.exe`, `combine_*`, docs, `*.jar`).

## Setup (Windows, Python 3.10+)

```bat
cd F:\projects\helper-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
notepad config.json
```

## Config (`config.json`)

```json
{
  "provider": "gemini",
  "fallback_enabled": true,
  "fallback_order": ["gemini", "openai", "claude"],
  "gemini": { "api_key": "KEY-1", "model": "gemini-2.5-flash" },
  "openai": { "api_key": "KEY-2", "model": "gpt-5-mini-2025-08-07" },
  "claude": { "api_key": "KEY-3", "model": "claude-sonnet-4-20250514" },
  "prompt": { "prefix": "...", "style": "...", "system": "..." },
  "ocr": { "langs": "eng+rus", "psm": 3 },
  "window": { "position": "top-right", "opacity": 0.55, "width": 200, "height": 50, "x": null, "y": null, "margin": 10 }
}
```

- `provider` — primary LLM. If its key fails/quota and `fallback_enabled` is true, tries the rest of `fallback_order` in order. Providers with empty keys are skipped. UI stays neutral (`pipi pupu` / `...`), errors go to console.
- `prompt` — request = `{prefix}{clipboard/OCR text}\n\n{style}`, system prompt sent separately.
- `ocr.langs` — `eng+rus` (both traineddata files bundled).
- `window` — `position`: `top-right|top-left|bottom-left|bottom-right` + `margin` px; `x`+`y` set together override the preset; `width`/`height`/`opacity` apply on next start.

`.env` vars still work as fallback (`PROVIDER`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).

## Run (dev)

```bat
.venv\Scripts\python pipipupu.py
```

- Copy text → answer appears in the floating window
- Triple-click → fullscreen OCR → clipboard → answer
- Drag to move, double-click to close

## Compile to EXE (Windows)

Prereqs: the Setup steps above (venv + `pip install -r requirements.txt`, which includes `pyinstaller`).

```bat
.venv\Scripts\activate
pyinstaller pipipupu.spec
```

- Output: `dist\pipipupu.exe` (single file, windowed — no console).
- The spec bundles `tesseract/` (exe + DLLs + `tessdata/eng+rus/osd`) and `config.example.json`.
- First run: place `config.json` next to the exe (copy from `config.example.json` and fill keys), or set env vars. Without `config.json` the exe uses built-in defaults and env vars.
- Rebuild after any `pipipupu.py` change: run `pyinstaller pipipupu.spec` again. If the build behaves oddly, wipe caches first: `rmdir /s /q build dist` then rebuild.
- Size note: Qt + Tesseract DLLs make the exe large (~100–150 MB) — normal.

## Push edits (SSH)

```bat
git add -A
git commit -m "msg"
git push
```

Remote is `git@github.com:amir1330/helper-tool.git`. Never commit `config.json` / `.env` (both gitignored).
