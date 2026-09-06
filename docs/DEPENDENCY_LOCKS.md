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

Review the resulting version and hash changes before committing them. Runtime
integrations use the application's maintained HTTP clients; production locks do
not include dependencies fetched from mutable or non-indexed Git sources.

Docker base and test-only PostgreSQL references retain readable tags but are also
pinned to immutable manifest-list digests. An intentional image upgrade must
update the matching references in the Dockerfile, CI and local release-gate script.

GitHub Actions are pinned to full commit SHAs. Their trailing version comments are
human-readable update hints only; verify the upstream release and replace both the
SHA and comment deliberately when upgrading an Action.

The release gate builds the production image twice without cache and compares the
installed Python packages, Alpine packages and compiled frontend hashes:

```bash
./scripts/verify_reproducible_build.sh
```

Passing an image tag keeps the first verified build for subsequent checks; without
an argument both temporary images are removed.

CI then runs `scripts/smoke_production_image.sh` against that unchanged image,
using the job's external PostgreSQL 16 service. The smoke uses the production
entrypoint and command, waits for `/health/ready`, verifies UID/GID `1000:1000`
and prints container logs on failure.
