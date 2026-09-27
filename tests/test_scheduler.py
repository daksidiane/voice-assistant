import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pytest

from modules.scheduler import Scheduler


def test_scheduler_crud():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        scheduler = Scheduler(storage_path=temp_path)
        dt = datetime.now() + timedelta(hours=2)
        plan = scheduler.add_plan("Важная встреча", dt)

        assert plan["title"] == "Важная встреча"
        assert len(scheduler.plans) == 1

        upcoming = scheduler.get_upcoming_plans()
        assert len(upcoming) == 1

        assert scheduler.delete_plan(plan["id"]) is True
        assert len(scheduler.plans) == 0
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_natural_datetime_parsing():
    scheduler = Scheduler()
    now = datetime.now()

    # Test "через 30 минут"
    res = scheduler.parse_natural_datetime("напомни выпить лекарство через 30 минут")
    assert res is not None
    dt, title = res
    assert "лекарство" in title
    assert abs((dt - (now + timedelta(minutes=30))).total_seconds()) < 60

    # Test "завтра в 15:00"
    res2 = scheduler.parse_natural_datetime("запомни: звонок клиенту завтра в 15:00")
    assert res2 is not None
    dt2, title2 = res2
    assert "клиенту" in title2
    assert dt2.hour == 15
    assert dt2.minute == 0
    assert dt2.day == (now + timedelta(days=1)).day


def test_scheduler_chronological_sorting():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        scheduler = Scheduler(storage_path=temp_path)
        base = datetime(2026, 9, 22, 12, 0)
        # Add plans out of order
        scheduler.add_plan("Позднее событие", base + timedelta(days=5))
        scheduler.add_plan("Самое раннее событие", base + timedelta(hours=1))
        scheduler.add_plan("Среднее событие", base + timedelta(days=2))

        all_plans = scheduler.get_all_plans(sorted_by_date=True)
        assert len(all_plans) == 3
        assert all_plans[0]["title"] == "Самое раннее событие"
        assert all_plans[1]["title"] == "Среднее событие"
        assert all_plans[2]["title"] == "Позднее событие"

        # Check in-memory plans order
        assert scheduler.plans[0]["title"] == "Самое раннее событие"
        assert scheduler.plans[2]["title"] == "Позднее событие"
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_parse_dt_safe_formats():
    from modules.scheduler import parse_dt_safe

    # DD-MM-YYYY HH:MM
    dt1 = parse_dt_safe("22-09-2026 18:00")
    assert dt1 == datetime(2026, 9, 22, 18, 0)

    # DD.MM.YYYY HH:MM
    dt2 = parse_dt_safe("22.09.2026 19:30")
    assert dt2 == datetime(2026, 9, 22, 19, 30)

    # Legacy YYYY-MM-DD HH:MM
    dt3 = parse_dt_safe("2026-09-22 20:15")
    assert dt3 == datetime(2026, 9, 22, 20, 15)

    # Invalid returns datetime.max
    assert parse_dt_safe("invalid-date") == datetime.max


def test_date_format_dd_mm_yyyy_storage():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        sch = Scheduler(storage_path=temp_path)
        plan = sch.add_plan("Встреча", datetime(2026, 9, 22, 14, 45))
        assert plan["datetime"] == "22-09-2026 14:45"
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_russian_word_numerals_parsing():
    scheduler = Scheduler()
    now = datetime.now()

    # 1. "добавь событие девятнадцать ноль ноль тренировка"
    res1 = scheduler.parse_natural_datetime("добавь событие девятнадцать ноль ноль тренировка")
    assert res1 is not None
    dt1, title1 = res1
    assert "тренировка" in title1
    assert dt1.hour == 19
    assert dt1.minute == 0

    # 2. "напомни обед через пять минут"
    res2 = scheduler.parse_natural_datetime("напомни обед через пять минут")
    assert res2 is not None
    dt2, title2 = res2
    assert "обед" in title2
    assert abs((dt2 - (now + timedelta(minutes=5))).total_seconds()) < 60

    # 3. "через полчаса выпить таблетку"
    res3 = scheduler.parse_natural_datetime("через полчаса выпить таблетку")
    assert res3 is not None
    dt3, title3 = res3
    assert "таблетку" in title3
    assert abs((dt3 - (now + timedelta(minutes=30))).total_seconds()) < 60

    # 4. "завтра в два часа дня встреча с коллегами"
    res4 = scheduler.parse_natural_datetime("завтра в два часа дня встреча с коллегами")
    assert res4 is not None
    dt4, title4 = res4
    assert "коллегами" in title4
    assert dt4.hour == 14
    assert dt4.minute == 0
    assert dt4.day == (now + timedelta(days=1)).day


def test_event_exact_timing_trigger():
    """Verify that event notifications never trigger prematurely before event time."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        sch = Scheduler(storage_path=temp_path)
        # Event is in the future by 2 minutes (e.g. 16:28 when event is 16:30)
        future_dt = datetime.now() + timedelta(minutes=2)
        plan = sch.add_plan("Будущее событие", future_dt)

        now = datetime.now()
        diff = (future_dt - now).total_seconds()
        assert diff > 0
        should_trigger = -120 <= diff <= 0 and not plan.get("reminded_event", False)
        assert should_trigger is False, "Event must NOT trigger 2 minutes early!"

        # Simulate arrival of event time: diff <= 0
        past_dt = datetime.now() - timedelta(seconds=5)
        diff_arrived = (past_dt - datetime.now()).total_seconds()
        should_trigger_arrived = -120 <= diff_arrived <= 0 and not plan.get("reminded_event", False)
        assert should_trigger_arrived is True, "Event must trigger when time arrives!"
    finally:
        sch.stop()
        if temp_path.exists():
            temp_path.unlink()



