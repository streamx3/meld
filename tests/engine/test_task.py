import pytest

from meldq.engine.task import (
    FifoScheduler,
    LifoScheduler,
    RoundRobinScheduler,
    SchedulerBase,
    SchedulerEmpty,
)


def tagged_gen(log, tag, n=2):
    for i in range(n):
        log.append(f"{tag}{i}")
        yield 1


def test_fifo_runs_tasks_in_order():
    log = []
    s = FifoScheduler()
    s.add_task(tagged_gen(log, "A"))
    s.add_task(tagged_gen(log, "B"))
    s.complete_tasks()
    assert log == ["A0", "A1", "B0", "B1"]


def test_lifo_runs_most_recent_first():
    log = []
    s = LifoScheduler()
    s.add_task(tagged_gen(log, "A"))
    s.add_task(tagged_gen(log, "B"))
    s.complete_tasks()
    assert log == ["B0", "B1", "A0", "A1"]


def test_round_robin_interleaves():
    log = []
    s = RoundRobinScheduler()
    s.add_task(tagged_gen(log, "A"))
    s.add_task(tagged_gen(log, "B"))
    s.add_task(tagged_gen(log, "C"))
    s.complete_tasks()
    assert log[:6] == ["B0", "C0", "A0", "B1", "C1", "A1"]


def test_falsy_return_removes_callable():
    calls = []
    def two_shot():
        calls.append(1)
        return 1 if len(calls) < 2 else 0
    s = FifoScheduler()
    s.add_task(two_shot)
    s.complete_tasks()
    assert len(calls) == 2
    assert not s.tasks_pending()


def test_exhausted_generator_removed():
    s = FifoScheduler()
    s.add_task(tagged_gen([], "A", n=1))
    assert s.iteration() == 1
    assert s.iteration() == 0        # StopIteration -> removed
    assert not s.tasks_pending()


def test_raising_task_removed_others_survive(capsys):
    log = []
    def bad():
        raise ValueError("boom")
    s = FifoScheduler()
    s.add_task(bad)
    s.add_task(tagged_gen(log, "A"))
    s.complete_tasks()
    assert "ValueError: boom" in capsys.readouterr().err
    assert log == ["A0", "A1"]


def test_runnable_cb_fires_with_scheduler():
    hits = []
    s = FifoScheduler()
    s.runnable_cb = hits.append
    s.add_task(lambda: 0)
    assert hits == [s]


def test_add_scheduler_propagates_child():
    parent = LifoScheduler()
    child = FifoScheduler()
    parent.add_scheduler(child)
    assert not parent.tasks_pending()
    child.add_task(tagged_gen([], "A"))
    assert child in parent.tasks


def test_remove_scheduler_disconnects():
    # Regression for meld/task.py:87-89 — the 1.4 disconnect was a silent
    # no-op (callbacks held lambdas, not schedulers), so a closed document's
    # scheduler kept re-adding itself to the app pump.
    parent = LifoScheduler()
    child = FifoScheduler()
    parent.add_scheduler(child)
    child.add_task(tagged_gen([], "A"))
    assert child in parent.tasks
    parent.remove_scheduler(child)
    assert child not in parent.tasks
    child.add_task(tagged_gen([], "B"))
    assert child not in parent.tasks


def test_iteration_passes_through_strings_and_floats():
    def status():
        yield "scanning..."
        yield 0.5
    s = FifoScheduler()
    s.add_task(status())
    assert s.iteration() == "scanning..."
    assert s.iteration() == 0.5


def test_complete_tasks_drains():
    s = FifoScheduler()
    for tag in "ABC":
        s.add_task(tagged_gen([], tag))
    s.complete_tasks()
    assert not s.tasks_pending()


@pytest.mark.parametrize("cls", [FifoScheduler, LifoScheduler, RoundRobinScheduler])
def test_scheduler_empty_and_iteration_zero(cls):
    s = cls()
    with pytest.raises(SchedulerEmpty):
        s.get_current_task()
    assert s.iteration() == 0


def test_call_convention():
    # __call__ returns the task's own return if truthy, else tasks_pending()
    s = FifoScheduler()
    assert s() is False
    def status():
        yield "text"
        yield 1
    s.add_task(status())
    assert s() == "text"


def test_base_scheduler_is_abstract():
    with pytest.raises(NotImplementedError):
        SchedulerBase().get_current_task()
