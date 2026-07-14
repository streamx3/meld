### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>

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

"""Classes to implement scheduling for cooperative threads.
"""

import traceback
import types


class SchedulerEmpty(Exception):
    """Raised by get_current_task when the scheduler has no tasks."""


class SchedulerBase:
    """Base class with common functionality for schedulers.

    Derived classes should implement the 'get_current_task' method.
    """

    def __init__(self):
        """Create a scheduler with no current tasks.
        """
        self.tasks = []
        # callable(scheduler) | None; set by the owner (the pump, or a
        # parent scheduler via add_scheduler)
        self.runnable_cb = None
        # set by documents around modal exec(); the pump skips paused
        # schedulers
        self.paused = False

    def __repr__(self):
        return repr(self.tasks)

    def add_task(self, task, atfront=False):
        """Add 'task' to the task list.

        'task' may be a callable, a generator object, or a scheduler.
        The task is deemed to be finished when either it returns a
        false value or raises StopIteration.
        """
        try:
            self.tasks.remove(task)
        except ValueError:
            pass

        if atfront:
            self.tasks.insert(0, task)
        else:
            self.tasks.append(task)

        if self.runnable_cb is not None:
            self.runnable_cb(self)

    def remove_task(self, task):
        """Remove 'task'.
        """
        try:
            self.tasks.remove(task)
        except ValueError:
            pass

    def remove_all_tasks(self):
        """Remove all tasks.
        """
        self.tasks = []

    def add_scheduler(self, sched):
        """Calls add_task whenever 'sched' becomes runnable.
        """
        sched.runnable_cb = self.add_task

    def remove_scheduler(self, sched):
        """Remove 'sched' and stop listening for its tasks.
        """
        self.remove_task(sched)
        sched.runnable_cb = None

    def get_current_task(self):
        """Function overridden by derived classes.

        The usual implementation will be to call self._iteration(task) where
        'task' is one of self.tasks.
        """
        raise NotImplementedError("This method must be overridden by subclasses.")

    def __call__(self):
        """Check for pending tasks and run an iteration of the current task.
        """
        if len(self.tasks):
            r = self.iteration()
            if r:
                return r
        return self.tasks_pending()

    def complete_tasks(self):
        """Run all currently added tasks to completion.

        Tasks added after the call to complete_tasks are not run.
        """
        while self.tasks_pending():
            self.iteration()

    def tasks_pending(self):
        return len(self.tasks) != 0

    def iteration(self):
        """Perform one iteration of the current task..

        Calls self.get_current_task() to find the current task.
        Remove task from self.tasks if it is complete.
        """
        try:
            task = self.get_current_task()
        except SchedulerEmpty:
            return 0
        try:
            if isinstance(task, types.GeneratorType):
                ret = next(task)
            else:
                ret = task()
        except StopIteration:
            pass
        except Exception:
            traceback.print_exc()
        else:
            if ret:
                return ret
        self.tasks.remove(task)
        return 0


class LifoScheduler(SchedulerBase):
    """Most recently added tasks are called first.
    """
    def get_current_task(self):
        try:
            return self.tasks[-1]
        except IndexError:
            raise SchedulerEmpty


class FifoScheduler(SchedulerBase):
    """Subtasks are called in the order they were added.
    """
    def get_current_task(self):
        try:
            return self.tasks[0]
        except IndexError:
            raise SchedulerEmpty


class RoundRobinScheduler(SchedulerBase):
    """Each subtask is called in turn.
    """
    def get_current_task(self):
        try:
            self.tasks.append(self.tasks.pop(0))
            return self.tasks[0]
        except IndexError:
            raise SchedulerEmpty
