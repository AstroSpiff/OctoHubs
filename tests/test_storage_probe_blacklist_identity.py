"""Regression coverage for the complete Probe blacklist identity."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import DatabaseStorage, EmbyProbeBlacklist


def test_probe_blacklist_update_and_delete_use_complete_identity(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-blacklist.db'}"
    engine = create_engine(database_url, future=True)
    EmbyProbeBlacklist.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        assert storage.update_probe_blacklist(
            "green", "movie-1", "Movie", "Error A", "src-a", scope="libraries"
        ) == 1
        assert storage.update_probe_blacklist(
            "green", "movie-1", "Movie", "Error B", "src-b", scope="libraries"
        ) == 1
        assert storage.update_probe_blacklist(
            "green", "movie-1", "Movie", "Recent error", "src-a", scope="recent"
        ) == 1
        assert storage.update_probe_blacklist(
            "green", "movie-1", "Movie", "Error A again", "src-a", scope="libraries"
        ) == 2

        entries = storage.get_probe_blacklist("green")
        assert {
            (entry["scope"], entry["media_source_id"], entry["retry_count"])
            for entry in entries
        } == {
            ("libraries", "src-a", 2),
            ("libraries", "src-b", 1),
            ("recent", "src-a", 1),
        }

        storage.remove_from_probe_blacklist(
            "green",
            "movie-1",
            "src-a",
            scope="libraries",
        )

        remaining = storage.get_probe_blacklist("green")
        assert {
            (entry["scope"], entry["media_source_id"])
            for entry in remaining
        } == {
            ("libraries", "src-b"),
            ("recent", "src-a"),
        }

        assert storage.update_probe_blacklist(
            "green", "movie-2", "Movie 2", "No source", scope="libraries"
        ) == 1
        assert storage.update_probe_blacklist(
            "green", "movie-2", "Movie 2", "No source again", scope="libraries"
        ) == 2
        assert storage.update_probe_blacklist(
            "green", "movie-2", "Movie 2", "Recent no source", scope="recent"
        ) == 1
        storage.remove_from_probe_blacklist(
            "green",
            "movie-2",
            scope="libraries",
        )
        no_source_entries = [
            entry
            for entry in storage.get_probe_blacklist("green")
            if entry["item_id"] == "movie-2"
        ]
        assert [(entry["scope"], entry["media_source_id"]) for entry in no_source_entries] == [
            ("recent", None)
        ]
    finally:
        engine.dispose()
