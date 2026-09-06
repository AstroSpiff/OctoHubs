#!/usr/bin/env python3
"""Run the container entrypoint while holding its secret-bootstrap lock."""

from __future__ import annotations

import fcntl
import os
import sys


_LOCK_FD = 9
_LOCK_FD_ENV = "OCTOHUBS_SECRET_LOCK_FD"


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: container_secret_lock.py LOCK_FILE ENTRYPOINT [COMMAND ...]", file=sys.stderr)
        return 2

    lock_path, entrypoint, *command = sys.argv[1:]
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if descriptor != _LOCK_FD:
            os.dup2(descriptor, _LOCK_FD, inheritable=True)
            os.close(descriptor)
            descriptor = _LOCK_FD
        else:
            os.set_inheritable(descriptor, True)

        environment = os.environ.copy()
        environment[_LOCK_FD_ENV] = str(_LOCK_FD)
        os.execvpe("sh", ["sh", entrypoint, *command], environment)
    finally:
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
