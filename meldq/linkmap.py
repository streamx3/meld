### Copyright (C) 2002-2009 Stephen Kennedy <stevek@gnome.org>

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

"""Canvas between two panes drawing bezier connectors and merge-action icons.

The bezier/icon painting and hit-testing are completed in WP6 T6.8; this is
the constructible skeleton the FileDiff layout needs.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget


class LinkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFixedWidth(50)
        self._doc = None
        self._which = 0

    def setup(self, doc, which):
        self._doc = doc
        self._which = which
        self.update()

    def paintEvent(self, event):
        # Full painting lands in WP6 T6.8.
        pass
