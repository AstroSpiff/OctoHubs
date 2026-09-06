"""Docker runtime healthcheck contract."""

from __future__ import annotations

import pathlib
import unittest


class DockerHealthcheckTests(unittest.TestCase):
    def test_container_healthcheck_uses_application_readiness(self):
        dockerfile = pathlib.Path("Dockerfile").read_text(encoding="utf-8")
        compose = pathlib.Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("http://127.0.0.1:5050/health/ready", dockerfile)
        self.assertIn("urllib.request.urlopen", dockerfile)
        self.assertNotIn("socket.create_connection", dockerfile)
        self.assertIn("http://127.0.0.1:5050/health/ready", compose)
        self.assertNotIn("nginx", compose.lower())


if __name__ == "__main__":
    unittest.main()
