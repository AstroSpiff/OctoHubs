"""Resource limits shared by the streaming-search protocol and executor."""

MAX_SEARCH_FRAME_BYTES = 64 * 1024
MAX_SEARCH_INPUT_VARIANTS = 8
MAX_SEARCH_QUERY_LENGTH = 300
MAX_SEARCH_TASKS = 512
MAX_CONCURRENT_OUTBOUND_SEARCHES = 4
MAX_GLOBAL_OUTBOUND_SEARCHES = 8
SEARCH_START_FRAME_TIMEOUT_SECONDS = 15.0
SEARCH_OUTBOUND_TIMEOUT_SECONDS = 30.0
SEARCH_STREAM_TIMEOUT_SECONDS = 3 * 60.0


class SearchWorkloadLimitError(ValueError):
    """Raised when one streaming search exceeds its bounded workload."""


class SearchClientDisconnected(ConnectionError):
    """Raised to cancel remaining work after the client connection is gone."""
