"""Probe queue identity and atomic lease regressions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import DatabaseStorage
from core.storage.storage_models import EmbyProbeQueue
from core.storage.storage_models import _utcnow
from emby_probe.library_probe_execution import LibraryProbeExecutionMixin, _ProbeResult
from emby_probe.library_processing import LibraryProcessingWorker
from emby_probe.queue_leases import ProbeClaimLost, run_with_claim_renewal


def test_probe_queue_deduplicates_identity_and_claims_once(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-claims.db'}"
    engine = create_engine(database_url, future=True)
    EmbyProbeQueue.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    item = {
        "server_id": "server-1",
        "item_id": "item-1",
        "scope": "libraries",
        "media_source_id": "source-1",
        "name": "Movie",
    }

    storage.add_to_probe_queue([item, item])
    queue = storage.get_probe_queue("server-1", scope="libraries")

    assert len(queue) == 1
    first_claim = storage.claim_probe_queue_items([queue[0]["id"]])
    assert len(first_claim) == 1
    first_token = first_claim[0]["claim_token"]
    assert first_token
    assert storage.claim_probe_queue_items([queue[0]["id"]]) == []
    assert storage.renew_probe_queue_claim(queue[0]["id"], "not-owner") is False
    assert storage.complete_probe_queue_claim(queue[0]["id"], "not-owner") is False
    assert storage.release_probe_queue_claim(queue[0]["id"], first_token) is True

    second_claim = storage.claim_probe_queue_items([queue[0]["id"]])
    second_token = second_claim[0]["claim_token"]
    assert second_token != first_token
    assert storage.complete_probe_queue_claim(queue[0]["id"], first_token) is False
    assert storage.complete_probe_queue_claim(queue[0]["id"], second_token) is True
    assert storage.get_probe_queue("server-1", scope="libraries") == []
    storage.close()


def test_probe_queue_discovery_and_cleanup_preserve_an_active_claim(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-active-claim.db'}"
    engine = create_engine(database_url, future=True)
    EmbyProbeQueue.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    generic = {
        "server_id": "server-1",
        "item_id": "item-1",
        "scope": "libraries",
        "media_source_id": None,
        "name": "Movie",
    }
    storage.add_to_probe_queue([generic])
    queue_id = storage.get_probe_queue("server-1", scope="libraries")[0]["id"]
    claimed = storage.claim_probe_queue_items([queue_id])[0]

    storage.add_to_probe_queue([{**generic, "media_source_id": "source-1"}])

    queue = storage.get_probe_queue("server-1", scope="libraries")
    assert [(item["id"], item["media_source_id"]) for item in queue] == [(queue_id, None)]
    assert storage.remove_from_probe_queue("server-1", "item-1", scope="libraries") is False
    assert storage.clear_probe_queue("server-1", scope="libraries") == 0
    assert storage.renew_probe_queue_claim(queue_id, claimed["claim_token"]) is True
    assert storage.complete_probe_queue_claim(queue_id, claimed["claim_token"]) is True

    storage.add_to_probe_queue([{**generic, "media_source_id": "source-1"}])
    queue = storage.get_probe_queue("server-1", scope="libraries")
    assert [item["media_source_id"] for item in queue] == ["source-1"]
    storage.close()


def test_probe_queue_discovery_replaces_an_expired_generic_claim(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-expired-claim.db'}"
    engine = create_engine(database_url, future=True)
    EmbyProbeQueue.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    generic = {
        "server_id": "server-1",
        "item_id": "item-1",
        "scope": "libraries",
        "media_source_id": None,
        "name": "Movie",
    }
    storage.add_to_probe_queue([generic])
    queue_id = storage.get_probe_queue("server-1", scope="libraries")[0]["id"]
    storage.claim_probe_queue_items([queue_id])
    with storage._get_session() as session:
        entry = session.get(EmbyProbeQueue, queue_id)
        entry.claimed_at = _utcnow() - timedelta(days=1)
        session.commit()

    storage.add_to_probe_queue([{**generic, "media_source_id": "source-1"}])

    queue = storage.get_probe_queue("server-1", scope="libraries")
    assert [item["media_source_id"] for item in queue] == ["source-1"]
    storage.close()


def test_probe_worker_pages_past_a_fully_claimed_batch():
    class Database:
        rows = [{"id": item_id, "item_id": f"item-{item_id}"} for item_id in range(1, 7)]

        def get_probe_queue(self, _server_id, *, limit, cursor_id, **_kwargs):
            return [row for row in self.rows if row["id"] > cursor_id][:limit]

        def claim_probe_queue_items(self, ids):
            return [row for row in self.rows if row["id"] in ids and row["id"] >= 5]

    worker = object.__new__(LibraryProcessingWorker)
    worker.db = Database()
    worker.server_id = "server-1"
    worker.scope = "libraries"
    worker.queue_batch_size = 2
    worker.probe_parallelism = 1
    worker.blacklist = {}
    import threading

    worker.stop_flag = threading.Event()

    _page, claimed = worker._claim_next_processable(None)

    assert [item["id"] for item in claimed] == [5, 6]


def test_probe_claim_renewal_fails_closed_when_ownership_is_lost():
    import threading

    class Database:
        renewals = 0

        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            self.renewals += 1
            return False

    database = Database()
    stopped = threading.Event()

    with pytest.raises(ProbeClaimLost):
        run_with_claim_renewal(
            database,
            {"id": 1, "claim_token": "owner-a"},
            lambda: stopped.wait(0.5),
            interval_seconds=0.01,
            on_claim_lost=stopped.set,
        )

    assert stopped.is_set()
    assert database.renewals == 1


def test_probe_claim_renewal_fails_closed_when_renew_raises():
    import threading

    class Database:
        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            raise RuntimeError("database unavailable")

    stopped = threading.Event()

    with pytest.raises(ProbeClaimLost):
        run_with_claim_renewal(
            Database(),
            {"id": 1, "claim_token": "owner-a"},
            lambda: stopped.wait(0.5),
            interval_seconds=0.01,
            on_claim_lost=stopped.set,
        )

    assert stopped.is_set()


def test_probe_result_is_not_persisted_after_final_ownership_check_fails():
    import threading

    class Database:
        mutations = 0

        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            return False

        def remove_from_probe_blacklist(self, *_args, **_kwargs):
            self.mutations += 1

        def add_probe_history(self, _payload):
            self.mutations += 1

    class Manager:
        def _update_status(self, *_args, **_kwargs):
            return None

    class Worker(LibraryProbeExecutionMixin):
        def _retry_count(self, _item):
            return 0

        def _wait_if_paused(self):
            return False

        def _wait_until_server_available(self):
            return True

        def _publish_item_start(self, _queue_item):
            return None

        def _probe(self, _queue_item):
            return _ProbeResult("SUCCESS", None, False, 1, 0)

    worker = Worker()
    worker.db = Database()
    worker.db_write_lock = threading.Lock()
    worker.stop_flag = threading.Event()
    worker.manager = Manager()
    worker.server_id = "server-1"
    worker.status_key = "libraries_processing"
    worker.scope = "libraries"

    assert worker._handle_queue_item({"id": 1, "claim_token": "owner-a"}) is False
    assert worker.stop_flag.is_set()
    assert worker.db.mutations == 0


def test_probe_worker_releases_a_claim_when_stop_prevents_processing():
    import threading

    class Database:
        released = []

        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            return True

        def release_probe_queue_claim(self, entry_id, claim_token):
            self.released.append((entry_id, claim_token))
            return True

    class Manager:
        def _update_status(self, *_args, **_kwargs):
            return None

    class Worker(LibraryProbeExecutionMixin):
        def _retry_count(self, _item):
            return 0

        def _wait_if_paused(self):
            return False

    worker = Worker()
    worker.db = Database()
    worker.db_write_lock = threading.Lock()
    worker.stop_flag = threading.Event()
    worker.stop_flag.set()
    worker.manager = Manager()
    worker.server_id = "server-1"
    worker.status_key = "libraries_processing"
    worker.scope = "libraries"

    assert worker._handle_queue_item({"id": 7, "claim_token": "owned"}) is False
    assert worker.db.released == [(7, "owned")]


def test_parallel_probe_releases_claims_that_never_enter_the_pool():
    import threading
    import time

    class Manager:
        def _update_status(self, *_args, **_kwargs):
            return None

    class Worker(LibraryProbeExecutionMixin):
        released = []

        def _handle_queue_item(self, item):
            if item["id"] == 1:
                return False
            time.sleep(0.05)
            return True

        def _release_claim(self, item, _claim_finished=None):
            self.released.append(item["id"])

        def _publish_active_slots(self, *_args, **_kwargs):
            return None

    worker = Worker()
    worker.manager = Manager()
    worker.server_id = "server-1"
    worker.status_key = "libraries_processing"
    worker.stop_flag = threading.Event()
    worker.probe_parallelism = 2

    assert worker._handle_queue_items_parallel([{"id": 1}, {"id": 2}, {"id": 3}]) is False
    assert worker.released == [3]
