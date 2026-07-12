from meldq.app import SchedulerPump
from meldq.engine.task import FifoScheduler


def test_full_task_lifecycle_and_idle(qtbot):
    pump = SchedulerPump()
    sched = FifoScheduler()

    def task():
        yield 0.25
        yield "working"
        yield 1

    fractions, messages, pulses, idle = [], [], [], []
    pump.progress_fraction.connect(fractions.append)
    pump.status_message.connect(messages.append)
    pump.progress_pulse.connect(lambda: pulses.append(1))
    pump.idle_changed.connect(idle.append)

    sched.add_task(task())
    pump.set_scheduler(sched)
    qtbot.waitUntil(lambda: not pump._timer.isActive(), timeout=2000)

    assert idle == [False, True]         # busy on start, idle when drained
    assert 0.25 in fractions
    assert "working" in messages
    assert len(pulses) == 1
    assert messages[-1] == ""            # cleared on idle
    assert fractions[-1] == 0.0
    assert pump._timer.isActive() is False   # no busy-spin at idle


def test_added_task_restarts_timer(qtbot):
    pump = SchedulerPump()
    sched = FifoScheduler()
    pump.set_scheduler(sched)
    assert not pump._timer.isActive()

    done = []
    def task():
        done.append(1)
        yield 1

    sched.add_task(task())               # runnable_cb should restart pumping
    assert pump._timer.isActive()
    qtbot.waitUntil(lambda: not pump._timer.isActive(), timeout=2000)
    assert done == [1]


def test_pause_and_resume(qtbot):
    pump = SchedulerPump()
    sched = FifoScheduler()
    counter = []

    def task():
        for _ in range(50):
            counter.append(1)
            yield 1

    sched.add_task(task())
    pump.set_scheduler(sched)
    qtbot.wait(30)
    pump.pause()
    frozen = len(counter)
    qtbot.wait(50)
    assert len(counter) == frozen        # no ticks while paused
    pump.resume()
    qtbot.waitUntil(lambda: not pump._timer.isActive(), timeout=2000)
    assert len(counter) == 50            # finished after resume


def test_set_scheduler_detaches_old(qtbot):
    pump = SchedulerPump()
    old = FifoScheduler()
    new = FifoScheduler()
    pump.set_scheduler(old)
    pump.set_scheduler(new)
    assert old.runnable_cb is None

    ticked = []
    def task():
        ticked.append(1)
        yield 1

    old.add_task(task())                 # detached: must not pump
    qtbot.wait(50)
    assert ticked == []
