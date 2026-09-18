"""Regression coverage for lazy, unbounded Probe queue title summaries."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import DatabaseStorage
from core.storage.storage_models import EmbyProbeQueue
from emby_probe import snapshots
from emby_probe.display import (
    _format_display_name_from_queue,
    normalize_probe_record_name,
)
from emby_probe.series_metadata import apply_series_metadata, resolve_series_metadata


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
                title=f"Film {index:03d}",
                year=2026,
                media_type="Movie",
                path=f"/movies/{index}.mkv",
            )
            for index in range(205)
        ]
        rows.append(
            EmbyProbeQueue(
                server_id="green",
                item_id="movie-0-alt",
                media_source_id="source-0-alt",
                scope="libraries",
                library_id="movies",
                library_name="Film",
                name="Film 000",
                title="Film 000",
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
                    series_year_resolved=True,
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
    movie = next(group for group in groups if group["group_id"] == "film 000")
    series = next(group for group in groups if group["group_type"] == "series")
    assert movie["file_count"] == 2
    assert series["title"] == "Serie completa"
    assert series["file_count"] == 2
    assert series["year"] == 2025

    movie_items = storage.get_probe_queue_group_items(
        "green",
        scope="libraries",
        group_type="movie",
        group_id="film 000",
        library_id="movies",
        year=2026,
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


def test_series_year_comes_from_series_object_not_remaining_episode_year():
    episodes = [
        {
            "Id": "episode-s03",
            "Type": "Episode",
            "SeriesId": "series-12-monkeys",
            "SeriesName": "12 Monkeys",
            "ProductionYear": 2017,
        }
    ]

    def call_emby_api(_server, path, *, method="GET", params):
        assert (path, method) == ("Items", "GET")
        assert params["Ids"] == "series-12-monkeys"
        return True, {
            "Items": [
                {
                    "Id": "series-12-monkeys",
                    "Type": "Series",
                    "Name": "12 Monkeys",
                    "ProductionYear": 2015,
                }
            ]
        }

    resolved = resolve_series_metadata(
        {"id": "green"},
        episodes,
        call_emby_api=call_emby_api,
    )
    apply_series_metadata(episodes, resolved)

    assert episodes[0]["SeriesProductionYear"] == 2015
    assert episodes[0]["series_year_resolved"] is True


def test_resolved_series_year_remains_stable_as_queue_rows_are_consumed(tmp_path):
    storage = _storage(tmp_path)
    storage.add_to_probe_queue(
        [
            {
                "server_id": "green",
                "item_id": "episode-s01",
                "scope": "libraries",
                "library_id": "series",
                "library_name": "Serie TV",
                "name": "12 Monkeys (2015) - S01E01",
                "series_name": "12 Monkeys",
                "season_number": 1,
                "episode_number": 1,
                "year": 2015,
                "media_type": "Episode",
            },
            {
                "server_id": "green",
                "item_id": "episode-s03",
                "scope": "libraries",
                "library_id": "series",
                "library_name": "Serie TV",
                "name": "12 Monkeys (2017) - S03E01",
                "series_name": "12 Monkeys",
                "season_number": 3,
                "episode_number": 1,
                "year": 2017,
                "media_type": "Episode",
            },
        ]
    )

    unresolved = storage.get_probe_queue_groups("green", scope="libraries")
    assert unresolved[0]["year"] is None

    assert storage.resolve_probe_series_metadata(
        "green",
        scope="libraries",
        metadata=[
            {
                "library_id": "series",
                "series_name": "12 Monkeys",
                "series_id": "series-12-monkeys",
                "year": 2015,
            }
        ],
    ) == 2
    assert storage.remove_from_probe_queue(
        "green",
        "episode-s01",
        None,
        scope="libraries",
    )

    groups = storage.get_probe_queue_groups("green", scope="libraries")
    assert groups[0]["title"] == "12 Monkeys"
    assert groups[0]["year"] == 2015
    storage.close()


def test_episode_queue_display_formats_raw_title_and_path_once():
    display = _format_display_name_from_queue(
        {
            "media_type": "Episode",
            "series_name": "Alphas",
            "season_number": 1,
            "episode_number": 2,
            "year": 2011,
            "title": "Causa ed effetto",
            "name": "Alphas (2011) - S01E02 - duplicated legacy value",
            "path": (
                "/media/Alphas (2011)/Season 1/"
                "Alphas (2011) - S01E02 - Causa ed effetto - 1080p.strm"
            ),
        }
    )

    assert display == "Alphas (2011) - S01E02 - Causa ed effetto - 1080p"
    assert display.count("Alphas (2011)") == 1
    assert display.count("Causa ed effetto") == 1


def test_existing_history_display_collapses_recursively_duplicated_suffix():
    stored = (
        "Alphas (2011) - S01E02 - Alphas (2011) - S01E02 - Cause & Effect - "
        "Causa ed effetto - 1080p x265 - Causa ed effetto - 1080p x265"
    )

    assert normalize_probe_record_name(stored) == (
        "Alphas (2011) - S01E02 - Causa ed effetto - 1080p x265"
    )


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
