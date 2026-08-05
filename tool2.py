import sys
import os
import threading
import requests
import time
import io

# --- NEW IMPORTS for OCR ---
import pytesseract
from PIL import Image
from pynput import mouse
# --- END NEW IMPORTS ---

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QBuffer, QIODevice
from PyQt6.QtGui import QGuiApplication

APP_NAME = "tool"
WINDOW_TITLE = "tool"

PROMPT_PREFIX = "Only letters of answer, no explanation. Keep it very short. "
RESPONSE_STYLE = "Respond VERY briefly. Max 2 sentences."
MODEL_NAME = "gpt-5-mini-2025-08-07"
TEMPERATURE = 1
MIN_CLIPBOARD_LEN = 3
DEBOUNCE_SECONDS = 0.5

# --- NEW: Triple-click settings ---
TRIPLE_CLICK_THRESHOLD_SEC = 0.4 # Max time between clicks


class MainWindow(QWidget):
    responseReady = pyqtSignal(str)
    # --- NEW: Signals for OCR ---
    tripleClickDetected = pyqtSignal()
    ocrTextReady = pyqtSignal(str)
    # --- END NEW SIGNALS ---

    def __init__(self):
        super().__init__()

        # --- Window configuration ---
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.X11BypassWindowManagerHint 
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setStyleSheet("background: transparent;")
        self.setFixedSize(200, 50)
        self.setWindowTitle(WINDOW_TITLE)

        # --- Label setup ---
        self.label = QLabel("Copy text...")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setStyleSheet("background: transparent; color: #DDDDDD; font-size: 13px;")

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.label)
        self.setLayout(layout)

        # --- Internal vars ---
        self._last_clip_text = ""
        self._inflight = False
        self._drag_pos = None
        
        # --- NEW: OCR click tracking ---
        self._click_times = []
        # --- END NEW OCR ---

        # --- Signals ---
        self.responseReady.connect(self._on_response_ready)
        # --- NEW: Connect OCR signals ---
        self.tripleClickDetected.connect(self._on_triple_click)
        self.ocrTextReady.connect(self._on_ocr_text_ready)
        # --- END NEW OCR ---

        # --- Initial clipboard check ---
        QTimer.singleShot(150, self._send_last_clipboard_once)

        # --- Poll clipboard ---
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(int(DEBOUNCE_SECONDS * 1000))
        self.poll_timer.timeout.connect(self._poll_clipboard)
        self.poll_timer.start()

        # --- Place and ensure on top ---
        QTimer.singleShot(0, self._place_initial)
        QTimer.singleShot(100, self.bring_to_front)

        # --- Periodic stay-on-top refresh ---
        self.keep_on_top_timer = QTimer(self)
        self.keep_on_top_timer.timeout.connect(self.bring_to_front)
        self.keep_on_top_timer.start(2000)  # every 2 seconds
        
        # --- NEW: Start global mouse listener ---
        # This runs in a separate thread to not block the GUI
        self._click_listener = mouse.Listener(on_click=self._on_global_click)
        threading.Thread(target=self._click_listener.start, daemon=True).start()
        # --- END NEW ---

    def bring_to_front(self):
        """Ensure the window stays visible on top even after clicks."""
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

    # --- Draggable behavior ---
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

    # --- Double-click to close ---
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()

    # ---------------------------
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
            self.label.setText("S...")
            threading.Thread(target=self._fetch_gpt, args=(text,), daemon=True).start()

    def _poll_clipboard(self):
        text = self._get_clipboard_text()
        if len(text) < MIN_CLIPBOARD_LEN or text == self._last_clip_text or self._inflight:
            return
        self._last_clip_text = text
        self._inflight = True
        self.label.setText("S...")
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

    # --- NEW: All functions below this line are new for the OCR ---

    def _on_global_click(self, x, y, button, pressed):
        """
        Listens for global mouse clicks to detect a triple-click.
        This runs in the pynput thread.
        """
        if button == mouse.Button.left and pressed:
            current_time = time.time()
            
            # Clean up old clicks
            self._click_times = [
                t for t in self._click_times 
                if current_time - t < TRIPLE_CLICK_THRESHOLD_SEC
            ]
            
            # Add this click
            self._click_times.append(current_time)
            
            # Check for triple click
            if len(self._click_times) == 3:
                # Emit signal to main GUI thread
                self.tripleClickDetected.emit()
                self._click_times.clear()

    def _on_triple_click(self):
        """
        Slot that runs in the main GUI thread when a triple-click is detected.
        Starts the OCR process in a new worker thread.
        """
        self.label.setText("..")
        self.bring_to_front()
        # Run the slow OCR work in a separate thread
        threading.Thread(target=self._perform_ocr, daemon=True).start()

    def _perform_ocr(self):
        """
        Runs in a worker thread.
        Grabs the screen, performs OCR, and emits the result.
        """
        try:
            # 1. Grab the screen
            # Note: This part *must* be done via the main thread's event loop
            # or be thread-safe. QGuiApplication.primaryScreen() is
            # generally safe to call, but we'll be careful.
            # A more robust way might involve passing the pixmap from the main thread,
            # but this is simpler and often works.
            scr = QGuiApplication.primaryScreen()
            if not scr:
                self.ocrTextReady.emit("OCR Error: No screen.")
                return
                
            pixmap = scr.grabWindow(0)
            
            # 2. Convert QPixmap to PIL Image for Pytesseract
            qimage = pixmap.toImage()
            buffer = QBuffer()
            # Use QIODevice.OpenModeFlag
            buffer.open(QIODevice.OpenModeFlag.WriteOnly) 
            qimage.save(buffer, "PNG")
            pil_image = Image.open(io.BytesIO(buffer.data()))
            
            # 3. Perform OCR
            text = pytesseract.image_to_string(pil_image)
            
            # 4. Emit signal with the text
            self.ocrTextReady.emit(text.strip())
            
        except Exception as e:
            self.ocrTextReady.emit(f"OCR Error: {e}")

    def _on_ocr_text_ready(self, text: str):
        """
        Slot that runs in the main GUI thread when OCR is complete.
        Copies the text to the clipboard.
        """
        if text:
            QApplication.clipboard().setText(text)
            self.label.setText(".")
        else:
            self.label.setText(".")
            
        self.bring_to_front()
        # The main app's _poll_clipboard will now pick up this new text
        # and trigger the _fetch_gpt logic.


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    w.raise_()
    w.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
