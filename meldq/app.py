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

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class SchedulerPump(QObject):
    """Drives one scheduler's cooperative tasks from a 0-interval QTimer.

    Replaces the 1.4 gobject.idle_add pump. Only the current tab's
    scheduler is driven; the timer stops when no tasks are pending (so it
    never busy-spins) and restarts from the scheduler's runnable callback.
    """

    status_message = pyqtSignal(str)      # on_idle str branch  (meldapp.py:265-266)
    progress_fraction = pyqtSignal(float)  # float branch        (meldapp.py:267-268)
    progress_pulse = pyqtSignal()         # other-truthy branch (meldapp.py:269-270)
    idle_changed = pyqtSignal(bool)       # True = no tasks pending

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)
        self._scheduler = None

    def set_scheduler(self, scheduler):
        if self._scheduler is not None:
            self._scheduler.runnable_cb = None
        self._scheduler = scheduler
        if scheduler is None:
            self._timer.stop()
            return
        scheduler.runnable_cb = self._on_runnable
        if scheduler.tasks_pending():
            if not self._timer.isActive():
                self._timer.start()
            self.idle_changed.emit(False)
        else:
            self._timer.stop()

    def pause(self):
        self._timer.stop()

    def resume(self):
        if self._scheduler is not None and self._scheduler.tasks_pending():
            self._timer.start()

    def stop(self):
        if self._scheduler is not None:
            self._scheduler.runnable_cb = None
        self._scheduler = None
        self._timer.stop()

    def _on_runnable(self, sched):
        if getattr(self._scheduler, "paused", False):
            return
        if not self._timer.isActive():
            self._timer.start()
        self.idle_changed.emit(False)

    def _tick(self):
        if self._scheduler is None:
            self._timer.stop()
            return
        if getattr(self._scheduler, "paused", False):
            self._timer.stop()
            return
        ret = self._scheduler.iteration()
        if isinstance(ret, str):
            self.status_message.emit(ret)
        elif type(ret) is float:
            self.progress_fraction.emit(ret)
        elif ret:
            self.progress_pulse.emit()
        if not self._scheduler.tasks_pending():
            self._timer.stop()
            self.status_message.emit("")
            self.progress_fraction.emit(0.0)
            self.idle_changed.emit(True)
