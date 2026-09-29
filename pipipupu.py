#!/usr/bin/env python3
"""
Combined GPT clipboard assistant + invisible OCR for Windows.
Click 3 times to OCR screenshot and copy text. Also shows small floating GPT window.
Tesseract is bundled in ./tesseract directory for portability.
"""

import sys
import os
import time
import json
import threading
import requests
from dotenv import load_dotenv
load_dotenv()
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QGuiApplication
from pynput import mouse
from PIL import ImageGrab
import pytesseract
import pyperclip

# --- Config (config.json + env fallback) ---
def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config() -> dict:
    defaults = {
        "provider": "gemini",
        "fallback_enabled": True,
        "fallback_order": ["gemini", "openai", "claude"],
        "gemini": {"api_key": "", "model": "gemini-2.5-flash", "temperature": 1.0, "max_output_tokens": 200},
        "openai": {"api_key": "", "model": "gpt-5-mini-2025-08-07",
                   "base_url": "https://api.openai.com/v1/chat/completions", "temperature": 1.0},
        "claude": {"api_key": "", "model": "claude-sonnet-4-20250514",
                   "base_url": "https://api.anthropic.com/v1/messages", "max_tokens": 200},
        "prompt": {"prefix": "Only letters of answer, no explanation. Keep it very short. ",
                   "style": "Respond VERY briefly. Max 2 sentences.",
                   "system": "You are a concise, helpful assistant."},
        "ocr": {"langs": "eng+rus", "psm": 3},
        "window": {"position": "top-right", "opacity": 0.55, "width": 200, "height": 50,
                   "x": None, "y": None, "margin": 10},
    }
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                _deep_merge(defaults, json.load(f))
        except Exception as e:
            print(f"⚠️ config.json load failed: {e}")
    # env overrides (keep .env working)
    if os.environ.get("GEMINI_API_KEY"):
        defaults["gemini"]["api_key"] = os.environ["GEMINI_API_KEY"]
    if os.environ.get("GEMINI_API_KEYS"):
        extra = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
        cur = defaults["gemini"].get("api_keys", [])
        defaults["gemini"]["api_keys"] = [*cur, *extra]
    if os.environ.get("GEMINI_MODEL"):
        defaults["gemini"]["model"] = os.environ["GEMINI_MODEL"]
    if os.environ.get("OPENAI_API_KEY"):
        defaults["openai"]["api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("OPENAI_API_KEYS"):
        extra = [k.strip() for k in os.environ["OPENAI_API_KEYS"].split(",") if k.strip()]
        cur = defaults["openai"].get("api_keys", [])
        defaults["openai"]["api_keys"] = [*cur, *extra]
    if os.environ.get("ANTHROPIC_API_KEY"):
        defaults["claude"]["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEYS"):
        extra = [k.strip() for k in os.environ["ANTHROPIC_API_KEYS"].split(",") if k.strip()]
        cur = defaults["claude"].get("api_keys", [])
        defaults["claude"]["api_keys"] = [*cur, *extra]
    if os.environ.get("PROVIDER"):
        defaults["provider"] = os.environ["PROVIDER"].lower()
    return defaults


def get_api_keys(section: dict) -> list:
    """Collect api keys in order: api_key (str or list) + api_keys list. Dedup, skip empties."""
    keys: list = []
    single = section.get("api_key", "")
    if isinstance(single, list):
        keys.extend(single)
    elif isinstance(single, str) and single.strip():
        keys.append(single.strip())
    multi = section.get("api_keys", [])
    if isinstance(multi, list):
        keys.extend(multi)
    elif isinstance(multi, str) and multi.strip():
        keys.append(multi.strip())
    seen, out = set(), []
    for k in keys:
        k = k.strip() if isinstance(k, str) else k
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _should_try_next_key(status_code: int, body: str = "") -> bool:
    # Retry next key on auth / quota / server errors.
    # Note: Gemini returns 400 for invalid keys, so 400 is retryable too
    # (if the prompt itself is bad, all keys fail the same way and we stop after).
    if status_code == 400:
        b = (body or "").lower()
        if "key" in b or "api" in b or "auth" in b:
            return True
        return True  # still try next key; cheap and safe
    return status_code in (401, 402, 403, 429, 500, 502, 503, 504)


CONFIG = load_config()

# --- GPT / Clipboard window config (from config.json) ---
APP_NAME = "tool"
WINDOW_TITLE = "tool"
PROMPT_PREFIX = CONFIG["prompt"]["prefix"]
RESPONSE_STYLE = CONFIG["prompt"]["style"]
SYSTEM_PROMPT = CONFIG["prompt"]["system"]
PROVIDER = CONFIG.get("provider", "gemini").lower()
MODEL_NAME = CONFIG["openai"]["model"]
GEMINI_MODEL = CONFIG["gemini"]["model"]
TEMPERATURE = CONFIG["gemini"].get("temperature", 1.0)
OCR_LANGS = CONFIG["ocr"].get("langs", "eng+rus")
OCR_PSM = CONFIG["ocr"].get("psm", 3)
WIN_OPACITY = float(CONFIG["window"].get("opacity", 0.55))
WIN_W = int(CONFIG["window"].get("width", 200))
WIN_H = int(CONFIG["window"].get("height", 50))
WIN_POS = CONFIG["window"].get("position", "top-right")
WIN_X = CONFIG["window"].get("x", None)
WIN_Y = CONFIG["window"].get("y", None)
WIN_MARGIN = int(CONFIG["window"].get("margin", 10))
MIN_CLIPBOARD_LEN = 3
DEBOUNCE_SECONDS = 0.5

# --- OCR config ---
CLICK_COUNT_THRESHOLD = 3
CLICK_WINDOW_SECONDS = 2.0
SCREENSHOT_DELAY = 0.1
DEBUG_MODE = False

# ------------------------- OCR Class -------------------------
class InvisibleOCR:
    def __init__(self):
        self.click_times = []
        self.lock = threading.Lock()
        self.running = True
        self._setup_tesseract()

    def _setup_tesseract(self):
        """Use bundled Tesseract if available (with eng+rus tessdata)."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(__file__)

        tesseract_path = os.path.join(base_path, "tesseract", "tesseract.exe")
        tessdata_dir = os.path.join(base_path, "tesseract", "tessdata")
        if os.path.isdir(tessdata_dir):
            os.environ.setdefault("TESSDATA_PREFIX", tessdata_dir)
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            if DEBUG_MODE:
                print(f"Tesseract found at: {tesseract_path} langs={OCR_LANGS}")
        else:
            # fallback to default installed Tesseract
            possible_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    if DEBUG_MODE:
                        print(f"Tesseract found at: {path}")
                    break
            else:
                print("⚠️ Tesseract not found! Make sure it's bundled or installed.")
                sys.exit(1)

    def _take_screenshot(self):
        try:
            return ImageGrab.grab()
        except Exception as e:
            if DEBUG_MODE:
                print(f"Screenshot failed: {e}")
            return None

    def _copy_to_clipboard(self, text):
        try:
            pyperclip.copy(text)
            return True
        except Exception as e:
            if DEBUG_MODE:
                print(f"Clipboard copy failed: {e}")
            return False

    def on_click(self, x, y, button, pressed):
        if not pressed:
            return
        with self.lock:
            now = time.time()
            self.click_times.append(now)
            cutoff = now - CLICK_WINDOW_SECONDS
            self.click_times = [t for t in self.click_times if t > cutoff]
            if len(self.click_times) >= CLICK_COUNT_THRESHOLD:
                if DEBUG_MODE:
                    print("Triggering OCR...")
                self.click_times = []
                threading.Thread(target=self._capture_and_ocr, daemon=True).start()

    def _capture_and_ocr(self):
        time.sleep(SCREENSHOT_DELAY)
        screenshot = self._take_screenshot()
        if screenshot is None:
            if DEBUG_MODE:
                print("Screenshot failed")
            return
        try:
            config = f"--psm {OCR_PSM}" if OCR_PSM else ""
            text = pytesseract.image_to_string(screenshot, lang=OCR_LANGS, config=config).strip()
            if text:
                if DEBUG_MODE:
                    print(f"OCR Text: {text[:50]}...")
                self._copy_to_clipboard(text)
        except Exception as e:
            if DEBUG_MODE:
                print(f"OCR failed: {e}")

    def start(self):
        listener = mouse.Listener(on_click=self.on_click)
        listener.start()
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.running = False
            listener.stop()

# ------------------------- GPT Clipboard Window -------------------------
class MainWindow(QWidget):
    responseReady = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.X11BypassWindowManagerHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setStyleSheet("background: transparent;")
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowOpacity(WIN_OPACITY)

        # Neutral UI texts — no status leaks
        self.IDLE_TEXT = "pipi pupu"
        self.BUSY_TEXT = "..."

        self.label = QLabel(self.IDLE_TEXT)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setStyleSheet("background: transparent; color: rgba(221, 221, 221, 160); font-size: 13px;")

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.label)
        self.setLayout(layout)

        self._last_clip_text = ""
        self._inflight = False
        self._drag_pos = None
        self.responseReady.connect(self._on_response_ready)

        QTimer.singleShot(150, self._send_last_clipboard_once)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(int(DEBOUNCE_SECONDS * 1000))
        self.poll_timer.timeout.connect(self._poll_clipboard)
        self.poll_timer.start()

        QTimer.singleShot(0, self._place_initial)
        QTimer.singleShot(100, self.bring_to_front)
        self.keep_on_top_timer = QTimer(self)
        self.keep_on_top_timer.timeout.connect(self.bring_to_front)
        self.keep_on_top_timer.start(2000)

    def bring_to_front(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.X11BypassWindowManagerHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowOpacity(WIN_OPACITY)
        self.show()
        self.raise_()

    def _place_initial(self):
        try:
            # Explicit x/y wins over preset position
            if WIN_X is not None and WIN_Y is not None:
                self.move(int(WIN_X), int(WIN_Y))
                return
            scr = self.screen() or QGuiApplication.primaryScreen()
            if not scr:
                return
            g = scr.geometry()
            m = WIN_MARGIN
            pos = (WIN_POS or "top-right").lower()
            if pos == "top-left":
                x, y = g.x() + m, g.y() + m
            elif pos == "bottom-left":
                x, y = g.x() + m, g.y() + g.height() - self.height() - m
            elif pos == "bottom-right":
                x, y = g.x() + g.width() - self.width() - m, g.y() + g.height() - self.height() - m
            else:  # top-right
                x, y = g.x() + g.width() - self.width() - m, g.y() + m
            self.move(x, y)
        except Exception:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()

    def _on_response_ready(self, text: str):
        self._inflight = False
        self.label.setText(text)
        self.bring_to_front()

    def _get_clipboard_text(self) -> str:
        try:
            text = QApplication.clipboard().text().strip()
            return text if text else ""
        except Exception:
            return ""

    def _send_last_clipboard_once(self):
        text = self._get_clipboard_text()
        if len(text) >= MIN_CLIPBOARD_LEN and not self._inflight:
            self._last_clip_text = text
            self._inflight = True
            self.label.setText(self.BUSY_TEXT)
            threading.Thread(target=self._fetch_gpt, args=(text,), daemon=True).start()

    def _poll_clipboard(self):
        text = self._get_clipboard_text()
        if len(text) < MIN_CLIPBOARD_LEN or text == self._last_clip_text or self._inflight:
            return
        self._last_clip_text = text
        self._inflight = True
        self.label.setText(self.BUSY_TEXT)
        threading.Thread(target=self._fetch_gpt, args=(text,), daemon=True).start()

    def _fail_quiet(self, log_msg: str):
        # Log details to console, show only neutral dots in UI
        print(log_msg)
        self.responseReady.emit("...")

    def _fetch_gpt(self, clip_text: str):
        try:
            prompt = f"{PROMPT_PREFIX}{clip_text}\n\n{RESPONSE_STYLE}"
            primary = (CONFIG.get("provider") or "gemini").lower()
            if CONFIG.get("fallback_enabled", True):
                order = [primary] + [p for p in CONFIG.get("fallback_order", ["gemini", "openai", "claude"])
                                     if p != primary]
            else:
                order = [primary]
            for provider in order:
                if provider == "gemini":
                    if not get_api_keys(CONFIG["gemini"]):
                        print("Skip gemini: no key.")
                        continue
                    print(f"Trying provider: gemini ({CONFIG['gemini']['model']})")
                    if self._fetch_gemini(prompt):
                        return
                elif provider == "claude":
                    if not get_api_keys(CONFIG["claude"]):
                        print("Skip claude: no key.")
                        continue
                    print(f"Trying provider: claude ({CONFIG['claude']['model']})")
                    if self._fetch_claude(prompt):
                        return
                else:
                    if not get_api_keys(CONFIG["openai"]):
                        print("Skip openai: no key.")
                        continue
                    print(f"Trying provider: openai ({CONFIG['openai']['model']})")
                    if self._fetch_openai(prompt):
                        return
            self._fail_quiet("All providers failed (see console).")
        except Exception as e:
            self._fail_quiet(f"fetch error: {e}")

    def _fetch_gemini(self, prompt: str) -> bool:
        g = CONFIG["gemini"]
        keys = get_api_keys(g)
        if not keys:
            print("Gemini key missing (config.json).")
            return False
        last_err = ""
        for i, key in enumerate(keys):
            try:
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{g['model']}:generateContent?key={key}",
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": g.get("temperature", 1.0),
                                             "maxOutputTokens": g.get("max_output_tokens", 200)},
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if i > 0:
                        print(f"Gemini key #{i+1} worked (earlier keys failed).")
                    self.responseReady.emit(text)
                    return True
                last_err = f"Gemini error {resp.status_code}: {resp.text[:200]}"
                print(f"Gemini key #{i+1}/{len(keys)} failed: {last_err}")
                if not _should_try_next_key(resp.status_code, resp.text):
                    break
            except Exception as e:
                last_err = f"Gemini Error: {e}"
                print(f"Gemini key #{i+1}/{len(keys)} exception: {e}")
        print(last_err or "Gemini failed.")
        return False

    def _fetch_openai(self, prompt: str) -> bool:
        o = CONFIG["openai"]
        keys = get_api_keys(o)
        if not keys:
            print("OpenAI key missing (config.json).")
            return False
        last_err = ""
        for i, key in enumerate(keys):
            try:
                resp = requests.post(
                    o.get("base_url", "https://api.openai.com/v1/chat/completions"),
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": o.get("model", MODEL_NAME),
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": o.get("temperature", 1.0)
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    if i > 0:
                        print(f"OpenAI key #{i+1} worked.")
                    self.responseReady.emit(text)
                    return True
                last_err = f"OpenAI API error {resp.status_code}: {resp.text[:200]}"
                print(f"OpenAI key #{i+1}/{len(keys)} failed: {last_err}")
                if not _should_try_next_key(resp.status_code, resp.text):
                    break
            except Exception as e:
                last_err = f"OpenAI Error: {e}"
                print(f"OpenAI key #{i+1}/{len(keys)} exception: {e}")
        print(last_err or "OpenAI failed.")
        return False

    def _fetch_claude(self, prompt: str) -> bool:
        c = CONFIG["claude"]
        keys = get_api_keys(c)
        if not keys:
            print("Claude key missing (config.json).")
            return False
        last_err = ""
        for i, key in enumerate(keys):
            try:
                resp = requests.post(
                    c.get("base_url", "https://api.anthropic.com/v1/messages"),
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": c.get("model", "claude-sonnet-4-20250514"),
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": c.get("max_tokens", 200),
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
                    if i > 0:
                        print(f"Claude key #{i+1} worked.")
                    self.responseReady.emit(text or "...")
                    return True
                last_err = f"Claude error {resp.status_code}: {resp.text[:200]}"
                print(f"Claude key #{i+1}/{len(keys)} failed: {last_err}")
                if not _should_try_next_key(resp.status_code, resp.text):
                    break
            except Exception as e:
                last_err = f"Claude Error: {e}"
                print(f"Claude key #{i+1}/{len(keys)} exception: {e}")
        print(last_err or "Claude failed.")
        return False

# ------------------------- Main Entry -------------------------
def main():
    # Start OCR listener in background
    threading.Thread(target=lambda: InvisibleOCR().start(), daemon=True).start()

    # Start GUI
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    w.raise_()
    w.activateWindow()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
