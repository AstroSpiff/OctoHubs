"""Streaming diagnostics must keep context without reusable torrent secrets."""


def test_streaming_first_result_diagnostics_redact_download_credentials():
    from search.streaming import stream_result_reference_log_lines

    secret = "R6_PRIVATE_PASSKEY"
    lines = stream_result_reference_log_lines(
        {
            "magnet": f"magnet:?xt=urn:btih:{secret}&tr=https://tracker.example/{secret}",
            "torrent": f"https://indexer.example/download/{secret}.torrent?apikey={secret}",
            "web": f"https://admin:{secret}@indexer.example/details?apikey={secret}",
        }
    )

    rendered = "\n".join(lines)
    assert secret not in rendered
    assert "indexer.example" in rendered
    assert "[REDACTED]" in rendered
