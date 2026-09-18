"""Regression coverage for lazy, unbounded Probe queue title summaries."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import DatabaseStorage
from core.storage.storage_models import EmbyProbeQueue
from emby_probe import snapshots


def _storage(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-groups.db'}"
    engine = create_engine(database_url, future=True)
    EmbyProbeQueue.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    return storage


def test_probe_queue_summaries_are_unbounded_and_details_are_title_scoped(tmp_path):
    storage = _storage(tmp_path)
    session = storage._get_session()
    try:
        rows = [
            EmbyProbeQueue(
                server_id="green",
                item_id=f"movie-{index}",
                media_source_id=f"source-{index}",
                scope="libraries",
                library_id="movies",
                library_name="Film",
                name=f"Film {index:03d}",
                year=2026,
                media_type="Movie",
                path=f"/movies/{index}.mkv",
            )
            for index in range(205)
        ]
        rows.append(
            EmbyProbeQueue(
                server_id="green",
                item_id="movie-0",
                media_source_id="source-0-alt",
                scope="libraries",
                library_id="movies",
                library_name="Film",
                name="Film 000",
                year=2026,
                media_type="Movie",
                path="/movies/0-alt.mkv",
            )
        )
        rows.extend(
            [
                EmbyProbeQueue(
                    server_id="green",
                    item_id="episode-2",
                    media_source_id="episode-source-2",
                    scope="libraries",
                    library_id="series",
                    library_name="Serie TV",
                    name="Episodio 2",
                    series_name="Serie completa",
                    season_number=1,
                    episode_number=2,
                    year=2025,
                    media_type="Episode",
                    path="/series/s01e02.mkv",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="episode-1",
                    media_source_id="episode-source-1",
                    scope="libraries",
                    library_id="series",
                    library_name="Serie TV",
                    name="Episodio 1",
                    series_name="Serie completa",
                    season_number=1,
                    episode_number=1,
                    year=2026,
                    media_type="Episode",
                    path="/series/s01e01.mkv",
                ),
            ]
        )
        session.add_all(rows)
        session.commit()
    finally:
        session.close()

    groups = storage.get_probe_queue_groups("green", scope="libraries")

    assert len(groups) == 206
    assert all("path" not in group for group in groups)
    movie = next(group for group in groups if group["group_id"] == "movie-0")
    series = next(group for group in groups if group["group_type"] == "series")
    assert movie["file_count"] == 2
    assert series["title"] == "Serie completa"
    assert series["file_count"] == 2
    assert series["year"] == 2025

    movie_items = storage.get_probe_queue_group_items(
        "green",
        scope="libraries",
        group_type="movie",
        group_id="movie-0",
        library_id="movies",
        year=None,
    )
    series_items = storage.get_probe_queue_group_items(
        "green",
        scope="libraries",
        group_type="series",
        group_id="Serie completa",
        library_id="series",
        year=2025,
    )

    assert {item["path"] for item in movie_items} == {
        "/movies/0.mkv",
        "/movies/0-alt.mkv",
    }
    assert [item["episode_number"] for item in series_items] == [1, 2]
    assert {item["year"] for item in series_items} == {2025, 2026}
    storage.close()


def test_probe_queue_group_snapshots_do_not_apply_the_row_page_limit(monkeypatch):
    class Backend:
        def get_probe_queue_groups(self, server_id, *, scope):
            assert (server_id, scope) == ("green", "libraries")
            return [
                {
                    "server_id": "green",
                    "group_type": "movie",
                    "group_id": f"movie-{index}",
                    "title": f"Movie {index}",
                    "file_count": 1,
                }
                for index in range(275)
            ]

        def get_probe_queue_group_items(self, server_id, **kwargs):
            assert server_id == "green"
            assert kwargs == {
                "scope": "libraries",
                "group_type": "movie",
                "group_id": "movie-1",
                "library_id": "movies",
                "year": None,
            }
            return [{"item_id": "movie-1", "name": "Movie 1"}]

    monkeypatch.setattr(snapshots, "_ensure_db_backend", Backend)

    summary, summary_status = snapshots._probe_queue_groups_get_snapshot(
        "green", "libraries"
    )
    details, details_status = snapshots._probe_queue_group_items_get_snapshot(
        "green", "libraries", "movie", "movie-1", "movies", "null"
    )

    assert summary_status == details_status == 200
    assert len(summary["groups"]) == 275
    assert details["queue"][0]["display_name"] == "Movie 1"


def test_probe_processing_order_keeps_series_and_files_contiguous(tmp_path):
    storage = _storage(tmp_path)
    session = storage._get_session()
    try:
        session.add_all(
            [
                EmbyProbeQueue(
                    server_id="green",
                    item_id="series-b-s2e2",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Serie B episodio 2",
                    series_name="Serie B",
                    season_number=2,
                    episode_number=2,
                    media_type="Episode",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="movie-z",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Zeta Film",
                    media_type="Movie",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="series-a-s2e1",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Serie A episodio 3",
                    series_name="Serie A",
                    season_number=2,
                    episode_number=1,
                    media_type="Episode",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="series-a-s1e2",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Serie A episodio 2",
                    series_name="Serie A",
                    season_number=1,
                    episode_number=2,
                    media_type="Episode",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="movie-a",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Alfa Film",
                    media_type="Movie",
                ),
                EmbyProbeQueue(
                    server_id="green",
                    item_id="series-a-s1e1",
                    scope="libraries",
                    library_id="mixed",
                    library_name="Mista",
                    name="Serie A episodio 1",
                    series_name="Serie A",
                    season_number=1,
                    episode_number=1,
                    media_type="Episode",
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    queue = storage.get_probe_queue(
        "green",
        scope="libraries",
        processing_order=True,
    )

    assert [item["item_id"] for item in queue] == [
        "series-a-s1e1",
        "series-a-s1e2",
        "series-a-s2e1",
        "series-b-s2e2",
        "movie-a",
        "movie-z",
    ]
    storage.close()
