"""Connection URL construction for deployment-supplied PostgreSQL fields."""

from sqlalchemy.engine import make_url

from core.storage.storage_utils import _build_connection_url


def test_connection_url_supports_ipv6_and_escaped_identifiers():
    value = _build_connection_url(
        {
            "DRIVER": "postgresql+psycopg2",
            "HOST": "2001:db8::1",
            "PORT": "5432",
            "NAME": "db?x",
            "USER": "user:name/part",
            "PASSWORD": "p@ss:word",
            "PARAMS": "sslmode=require&application_name=OctoHubs",
        }
    )

    parsed = make_url(value)
    assert parsed.host == "2001:db8::1"
    assert parsed.port == 5432
    assert parsed.database == "db?x"
    assert parsed.username == "user:name/part"
    assert parsed.password == "p@ss:word"
    assert dict(parsed.query) == {
        "application_name": "OctoHubs",
        "sslmode": "require",
    }


def test_connection_url_accepts_bracketed_ipv6_without_double_brackets():
    value = _build_connection_url(
        {"HOST": "[2001:db8::2]", "NAME": "octohubs", "USER": "octohubs"}
    )

    assert make_url(value).host == "2001:db8::2"
