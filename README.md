# Pipipupu - GPT Clipboard Assistant + OCR

Triple-click to OCR any part of your screen and copy text to clipboard. Also shows a small floating GPT window that automatically answers clipboard content.

## Requirements

- Windows (the app uses Win32 APIs)
- Python 3.10+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (bundled in `tesseract/` directory)

## Install Dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file with your OpenAI API key:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-mini-2025-08-07
```

Or set the `OPENAI_API_KEY` environment variable.

## Run

```bash
python pipipupu.py
```

## Compile to EXE (PyInstaller)

```bash
pyinstaller pipipupu.spec
```

The compiled `.exe` will be placed in `dist/`. The spec file bundles the `tesseract/` directory for portability.

## How It Works

- **Triple-click anywhere** on screen to OCR and copy text to clipboard
- The floating GPT window polls clipboard changes and sends new text to OpenAI
- Drag the floating window to reposition it
- Double-click the floating window to close
