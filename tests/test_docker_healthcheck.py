"""Docker runtime healthcheck contract."""

from __future__ import annotations

import pathlib
import unittest


class DockerHealthcheckTests(unittest.TestCase):
    def test_container_healthcheck_uses_lightweight_port_probe(self):
        dockerfile = pathlib.Path("Dockerfile").read_text(encoding="utf-8")
        compose = pathlib.Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("socket.create_connection", dockerfile)
        self.assertIn("127.0.0.1", dockerfile)
        self.assertNotIn("localhost:5050/login", dockerfile)
        self.assertIn("socket.create_connection", compose)
        self.assertNotIn("localhost:5050/login", compose)


if __name__ == "__main__":
    unittest.main()
