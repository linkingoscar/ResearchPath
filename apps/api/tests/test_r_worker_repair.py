from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import cast

import pytest

from app.services import r_workers
from app.settings import get_settings


def test_repair_does_not_block_cancellation_or_duplicate_reserved_slots(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    created: list[int] = []

    class Worker:
        def __init__(self, ordinal):
            self.ordinal = ordinal
            self.alive = True

        def terminate(self, **_kwargs):
            self.alive = False

        def shutdown(self):
            self.terminate()

    def factory(_settings, ordinal, _cancel_event=None):
        created.append(ordinal)
        entered.set()
        assert release.wait(5)
        return Worker(ordinal)

    monkeypatch.setattr(r_workers, "_RWorkerProcess", factory)
    pool = r_workers.RWorkerPool(replace(get_settings(), r_worker_count=2))
    original = cast(r_workers._RWorkerProcess, Worker(1))
    pool._workers.append(original)
    pool._started = True
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            repair = executor.submit(pool._repair_capacity)
            try:
                assert entered.wait(2)
                # While the replacement R worker is starting, removing the current
                # worker must finish, and a second repair must not start slot 2.
                duplicate = executor.submit(pool._repair_capacity)
                duplicate.result(timeout=1)
                cancelled = executor.submit(pool._replace, original, repair_capacity=False)
                cancelled.result(timeout=1)
                assert not original.alive
                assert created == [2]
            finally:
                release.set()
            repair.result(timeout=2)
        assert len(pool._workers) == 1
        assert pool._starting_ordinals == set()
        pool._repair_capacity()
        assert sorted(worker.ordinal for worker in pool._workers) == [1, 2]
    finally:
        release.set()
        pool.close()


def test_cancelled_capacity_repair_releases_reservation(monkeypatch):
    pool = r_workers.RWorkerPool(replace(get_settings(), r_worker_count=1))
    event = threading.Event()

    def cancelled_start(_settings, _ordinal, cancel_event=None):
        assert cancel_event is event
        raise r_workers.RWorkerCancelled("cancelled during startup")

    monkeypatch.setattr(r_workers, "_RWorkerProcess", cancelled_start)
    try:
        with pytest.raises(r_workers.RWorkerCancelled):
            pool._repair_capacity(cancel_event=event)
        assert pool._starting_ordinals == set()
        assert pool._workers == []
    finally:
        pool.close()
