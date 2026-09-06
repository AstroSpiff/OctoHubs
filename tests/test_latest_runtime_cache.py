from unittest.mock import Mock, patch

from emby_latest.enrichment_sources import _OMDB_RATINGS_CACHE, _fetch_omdb_ratings
from emby_latest.runtime_cache import BoundedTTLCache


def test_bounded_ttl_cache_expires_and_evicts_lru_entries():
    now = [0.0]
    cache = BoundedTTLCache[str, str](
        max_entries=2,
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    cache["a"] = "A"
    cache["b"] = "B"
    assert cache["a"] == "A"
    cache["c"] = "C"
    assert "b" not in cache
    now[0] = 11.0
    assert len(cache) == 0


def test_force_omdb_bypasses_the_runtime_cache():
    _OMDB_RATINGS_CACHE.clear()
    _OMDB_RATINGS_CACHE["tt123:movie"] = {"imdb_rating": "1.0"}
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "Response": "True",
        "Type": "movie",
        "imdbRating": "8.2",
        "imdbVotes": "123",
    }
    with patch("emby_latest.enrichment_sources.requests.get", return_value=response) as request:
        result = _fetch_omdb_ratings(
            "tt123",
            ["secret"],
            expected_type="movie",
            force_refresh=True,
        )
    request.assert_called_once()
    assert result["imdb_rating"] == "8.2"
