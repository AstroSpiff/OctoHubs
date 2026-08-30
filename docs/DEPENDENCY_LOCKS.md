# Dependency and image locks

Production Python dependencies are declared in `requirements.in` and compiled into
`requirements.txt`. Test-only dependencies are declared separately in
`requirements-dev.in` and compiled into `requirements-dev.txt`. Both generated
files contain exact versions and SHA-256 hashes; installs must use
`--require-hashes`.

Regenerate both locks in the pinned Python 3.11 build environment:

```bash
./scripts/compile_dependency_locks.sh
```

Review the resulting version and hash changes before committing them. The PyTrakt
source URL is tied to an immutable commit in `requirements.in`; update that commit
deliberately when upgrading it.

Docker base, PostgreSQL and Nginx references retain readable tags but are also pinned
to immutable manifest-list digests. An intentional image upgrade must update the
matching references in the Dockerfile, Compose, CI and local release-gate script.

The release gate builds the production image twice without cache and compares the
installed Python packages, Alpine packages and compiled frontend hashes:

```bash
./scripts/verify_reproducible_build.sh
```

Passing an image tag keeps the first verified build for subsequent checks; without
an argument both temporary images are removed.
