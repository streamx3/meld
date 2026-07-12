### Copyright (C) 2008-2009 Kai Willadsen <kai.willadsen@gmail.com>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""In-pane message banner (gedit-style), replacing meld/ui/msgarea.py.

The GTK tooltip-style-theft paint hack is gone: Qt exposes tooltip colours
as first-class QPalette roles.
"""

import enum
import functools
import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class ResponseId(enum.IntEnum):     # exact GTK values — filediff compares these ints
    NONE = -1
    OK = -5
    CANCEL = -6
    CLOSE = -7
    HELP = -11


_ICON_FALLBACKS = {
    "dialog-information": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "dialog-warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "dialog-error": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "window-close": QStyle.StandardPixmap.SP_DialogCloseButton,
}


def _themed_icon(widget, name):
    icon = QIcon.fromTheme(name)
    if icon.isNull():
        fallback = _ICON_FALLBACKS.get(name)
        if fallback is not None:
            return widget.style().standardIcon(fallback)
    return icon


class MsgArea(QFrame):
    response = pyqtSignal(int)

    def __init__(self, buttons=None, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window,
                         palette.color(QPalette.ColorRole.ToolTipBase))
        palette.setColor(QPalette.ColorRole.WindowText,
                         palette.color(QPalette.ColorRole.ToolTipText))
        palette.setColor(QPalette.ColorRole.Text,
                         palette.color(QPalette.ColorRole.ToolTipText))
        self.setPalette(palette)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._buttons = {}
        self._icon_label = QLabel()
        self._content = QVBoxLayout()
        self._content.setSpacing(6)
        self._action_layout = QVBoxLayout()
        self._action_layout.setSpacing(4)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)
        layout.addWidget(self._icon_label)
        layout.addLayout(self._content, 1)
        layout.addLayout(self._action_layout)

        if buttons:
            for text, respid in buttons:
                self.add_button(text, respid)

    def add_button(self, text, respid):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(functools.partial(self.response.emit, int(respid)))
        self._buttons[int(respid)] = button
        self._action_layout.addWidget(button)
        return button

    def add_stock_button_with_text(self, text, icon_name, respid):
        button = self.add_button(text, respid)
        button.setIcon(_themed_icon(self, icon_name))
        return button

    def set_text_and_icon(self, icon_name, primary, secondary=None):
        self._icon_label.setPixmap(_themed_icon(self, icon_name).pixmap(20, 20))
        while self._content.count():
            item = self._content.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._content.addWidget(self._make_label("<b>%s</b>" % html.escape(primary)))
        if secondary:
            self._content.addWidget(
                self._make_label("<small>%s</small>" % html.escape(secondary)))

    @staticmethod
    def _make_label(text):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def set_response_sensitive(self, respid, sensitive):
        button = self._buttons.get(int(respid))
        if button is not None:
            button.setEnabled(sensitive)

    def set_default_response(self, respid):
        button = self._buttons.get(int(respid))
        if button is not None:
            button.setDefault(True)

    def button_for_response(self, respid):
        return self._buttons.get(int(respid))


class MsgAreaController(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._msgarea = None
        self._msg_id = None

    def has_message(self):
        return self._msgarea is not None

    def get_msg_id(self):
        return self._msg_id

    def set_msg_id(self, msgid):
        self._msg_id = msgid

    def clear(self):
        if self._msgarea is not None:
            self._layout.removeWidget(self._msgarea)
            self._msgarea.deleteLater()
            self._msgarea = None
        self._msg_id = None

    def new_from_text_and_icon(self, icon_name, primary, secondary=None, buttons=None):
        self.clear()
        area = MsgArea(buttons or (), self)
        area.set_text_and_icon(icon_name, primary, secondary)
        self._layout.addWidget(area)
        self._msgarea = area
        return area
