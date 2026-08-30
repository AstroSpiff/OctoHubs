from datetime import datetime, timedelta

import pytest

from core.tasks import AutoScheduler


def _config(scan_settings, **extra):
    return {
        "AUTO_TASKS": {"scan": scan_settings},
        **extra,
    }


@pytest.fixture
def scheduler():
    instance = AutoScheduler()
    instance.stop()
    instance._thread.join(timeout=1)
    assert instance._thread.is_alive() is False
    instance._config_logged = True
    return instance


def test_interval_change_recalculates_only_the_changed_task(scheduler):
    scheduler.update_config(_config({
        "enabled": True,
        "mode": "interval",
        "interval_minutes": 1440,
        "times": [],
    }))
    previous_scan_run = datetime.now() + timedelta(days=1)
    preserved_refresh_run = datetime.now() + timedelta(hours=2)
    scheduler._next_run["scan"] = previous_scan_run
    scheduler._next_run["refresh"] = preserved_refresh_run

    scheduler.update_config(_config({
        "enabled": True,
        "mode": "interval",
        "interval_minutes": 5,
        "times": [],
    }))

    assert scheduler._next_run["scan"] is None
    assert scheduler._next_run["refresh"] == preserved_refresh_run

    before_evaluation = datetime.now()
    scheduler._evaluate_tasks()
    recalculated_run = scheduler._next_run["scan"]
    assert recalculated_run is not None
    assert before_evaluation + timedelta(minutes=4, seconds=59) < recalculated_run
    assert recalculated_run <= datetime.now() + timedelta(minutes=5, seconds=1)


def test_fixed_time_change_recalculates_the_next_occurrence(scheduler):
    scheduler.update_config(_config({
        "enabled": True,
        "mode": "fixed",
        "interval_minutes": 60,
        "times": ["22:00"],
    }))
    scheduler._next_run["scan"] = datetime.now() + timedelta(days=1)

    scheduler.update_config(_config({
        "enabled": True,
        "mode": "fixed",
        "interval_minutes": 60,
        "times": ["06:15"],
    }))

    assert scheduler._next_run["scan"] is None
    scheduler._evaluate_tasks()
    recalculated_run = scheduler._next_run["scan"]
    assert recalculated_run is not None
    assert (recalculated_run.hour, recalculated_run.minute) == (6, 15)
    assert recalculated_run > datetime.now()


def test_enabled_transitions_discard_stale_deadlines(scheduler):
    disabled = {
        "enabled": False,
        "mode": "interval",
        "interval_minutes": 30,
        "times": [],
    }
    enabled = {**disabled, "enabled": True}
    scheduler.update_config(_config(disabled))
    scheduler._next_run["scan"] = datetime.now() + timedelta(days=1)

    scheduler.update_config(_config(enabled))
    assert scheduler._next_run["scan"] is None

    scheduler._evaluate_tasks()
    assert scheduler._next_run["scan"] is not None
    scheduler.update_config(_config(disabled))
    assert scheduler._next_run["scan"] is None


def test_unrelated_config_update_preserves_existing_deadlines(scheduler):
    scan_settings = {
        "enabled": True,
        "mode": "interval",
        "interval_minutes": 30,
        "times": [],
    }
    scheduler.update_config(_config(scan_settings, revision=1))
    existing_run = datetime.now() + timedelta(minutes=30)
    scheduler._next_run["scan"] = existing_run

    scheduler.update_config(_config(scan_settings, revision=2))

    assert scheduler._next_run["scan"] == existing_run
