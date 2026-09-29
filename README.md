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
  "network": { "proxy": "", "timeout": 30, "try_direct_first": true },
  "window": { "position": "top-right", "opacity": 0.55, "width": 200, "height": 50, "x": null, "y": null, "margin": 10 }
}
```

- `provider` — primary LLM. If its key fails/quota and `fallback_enabled` is true, tries the rest of `fallback_order` in order. Providers with empty keys are skipped. UI stays neutral (`pipi pupu` / `...`), errors go to console.
- `prompt` — request = `{prefix}{clipboard/OCR text}\n\n{style}`, system prompt sent separately.
- `ocr.langs` — `eng+rus` (both traineddata files bundled).
- `network.proxy` — empty = direct. Set `http://127.0.0.1:1080` (or `HTTP_PROXY` env) to auto-fallback via proxy when public wifi blocks AI APIs; `timeout` seconds per attempt.
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

Prereqs: Python 3.10+, venv with `pip install -r requirements.txt` (includes `pyinstaller`), `config.json` filled in.

```bat
.venv\Scripts\activate
pyinstaller pipipupu.spec
```

- Output: `dist\pipipupu.exe` (single file, windowed — no console).
- The spec bundles `tesseract/` (exe + DLLs + `tessdata/eng+rus/osd`) and your `config.json` as it is at build time.
- Flow: fill `config.json` → test with `python pipipupu.py` → build. Whatever is in your config at build time (keys, models, prompts, window, proxy) is baked in, so the exe runs anywhere with no external files. A `config.json`/`.env` placed next to the exe still overrides baked values if keys ever change.
- NOTE: the exe contains your API keys — don't share it publicly.
- Rebuild after any `pipipupu.py` change: run `pyinstaller pipipupu.spec` again. If the build behaves oddly, wipe caches first: `rmdir /s /q build dist` then rebuild.
- Size note: Qt + Tesseract DLLs make the exe large (~100–150 MB) — normal.
