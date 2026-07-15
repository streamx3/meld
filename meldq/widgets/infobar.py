"""InfoBar — a slim inline message banner with action buttons.

A lightweight stand-in for GTK's info bar / 3.24's MsgArea: a hidden-by-default
strip that shows one message plus optional [Button] actions (e.g. Reload /
Ignore for an on-disk change). FileDiff embeds one at the top; DirDiff and
VcView will reuse it for their warnings. Single message at a time for now.
"""

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class InfoBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 3, 6, 3)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._layout.addWidget(self._label, 1)
        self._buttons = []
        self._active = False        # a message is showing (independent of the
        self.setVisible(False)      # widget tree actually being on screen)

    def show_message(self, text, buttons=()):
        """Show `text` with optional buttons: a list of (label, callback).
        Clicking a button invokes its callback and dismisses the bar."""
        self._clear_buttons()
        self._active = True
        self._label.setText(text)
        for label, callback in buttons:
            btn = QPushButton(label)
            btn.clicked.connect(
                lambda _checked=False, cb=callback: self._invoke(cb))
            self._layout.addWidget(btn)
            self._buttons.append(btn)
        self.setVisible(True)

    def _invoke(self, callback):
        self.clear()
        if callback is not None:
            callback()

    def clear(self):
        self._active = False
        self._label.clear()
        self._clear_buttons()
        self.setVisible(False)

    @property
    def message(self):
        return self._label.text() if self._active else None

    def _clear_buttons(self):
        for btn in self._buttons:
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons = []
