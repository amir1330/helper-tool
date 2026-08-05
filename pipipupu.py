#!/usr/bin/env python3
"""
Combined GPT clipboard assistant + invisible OCR for Windows.
Click 3 times to OCR screenshot and copy text. Also shows small floating GPT window.
Tesseract is bundled in ./tesseract directory for portability.
"""

import sys
import os
import time
import threading
import requests
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QGuiApplication
from pynput import mouse
from PIL import ImageGrab
import pytesseract
import pyperclip

# --- GPT / Clipboard window config ---
APP_NAME = "tool"
WINDOW_TITLE = "tool"
PROMPT_PREFIX = "Only letters of answer, no explanation. Keep it very short. "
RESPONSE_STYLE = "Respond VERY briefly. Max 2 sentences."
MODEL_NAME = "gpt-5-mini-2025-08-07"
TEMPERATURE = 1
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
        """Use bundled Tesseract if available."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(__file__)

        tesseract_path = os.path.join(base_path, "tesseract", "tesseract.exe")
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            if DEBUG_MODE:
                print(f"Tesseract found at: {tesseract_path}")
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
            text = pytesseract.image_to_string(screenshot).strip()
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
        self.setFixedSize(200, 50)
        self.setWindowTitle(WINDOW_TITLE)

        self.label = QLabel("Copy text to send to GPT...")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setStyleSheet("background: transparent; color: #DDDDDD; font-size: 13px;")

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
        self.show()
        self.raise_()

    def _place_initial(self):
        try:
            scr = self.screen() or QGuiApplication.primaryScreen()
            if not scr:
                return
            g = scr.geometry()
            x = g.x() + 10
            y = g.y() + g.height() - self.height() - 10
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
            self.label.setText("Sending to GPT...")
            threading.Thread(target=self._fetch_gpt, args=(text,), daemon=True).start()

    def _poll_clipboard(self):
        text = self._get_clipboard_text()
        if len(text) < MIN_CLIPBOARD_LEN or text == self._last_clip_text or self._inflight:
            return
        self._last_clip_text = text
        self._inflight = True
        self.label.setText("Sending to GPT...")
        threading.Thread(target=self._fetch_gpt, args=(text,), daemon=True).start()

    def _fetch_gpt(self, clip_text: str):
        try:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                self.responseReady.emit("API key missing.")
                return
            prompt = f"{PROMPT_PREFIX}{clip_text}\n\n{RESPONSE_STYLE}"
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": "You are a concise, helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": TEMPERATURE
                },
                timeout=30,
            )
            if resp.status_code != 200:
                self.responseReady.emit(f"API error {resp.status_code}")
                return
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            self.responseReady.emit(text)
        except Exception as e:
            self.responseReady.emit(f"Error: {e}")

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
