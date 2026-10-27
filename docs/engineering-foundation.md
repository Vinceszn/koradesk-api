# Engineering checks

Use Python 3.13, matching the Docker runtime. The merchant workspace and legacy
service retain their separate entry points and database ownership. Alembic still
manages commerce tables only.

## Install and check

Create and activate a virtual environment, then run from the repository root:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m "not postgres"
python -m pip_audit -r requirements-dev.txt --require-hashes --disable-pip --progress-spinner off
```

`requirements.txt` contains only runtime dependencies; `requirements-dev.txt`
contains the complete runtime and development dependency set. Both pin transitive
versions and distribution hashes, including platform markers for Windows/Linux.
The Docker build also requires these hashes. No live WhatsApp, payment, or SMTP
credentials are required by the test suite.

Ruff checks syntax, imports, unused names, and basic correctness, and formats all
Python sources. Two narrowly scoped E402 exceptions preserve late router imports
and the preview script's environment setup before application imports.

## Live PostgreSQL tests

Start a separate, disposable local database:

```bash
docker compose -p koradesk-foundation -f compose.test.yml up -d --wait
```

Set the URL in the current shell. PowerShell:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://foundation:foundation@127.0.0.1:55432/koradesk_test"
python -m pytest -q -m postgres --require-postgres
```

macOS/Linux:

```bash
export TEST_DATABASE_URL='postgresql+psycopg://foundation:foundation@127.0.0.1:55432/koradesk_test'
python -m pytest -q -m postgres --require-postgres
```

You can instead supply an existing **test** PostgreSQL database. The role needs
permission to create and drop schemas. Each test creates a random schema, puts
both Alembic and application connections in that schema, then drops that schema
after disposing application connections. It never resets the supplied database
or drops existing schemas. Do not use a production URL.

`--require-postgres` fails immediately if the URL is absent; a bad URL or
unreachable database fails the tests. The default test run skips these four tests
when the variable is absent. To run everything with PostgreSQL configured:

```bash
python -m pytest -q --require-postgres
```

Coverage includes an upgrade/downgrade/re-upgrade preserving a legacy table;
database-enforced tenant foreign keys and rollback; competing PostgreSQL row
locks with a bounded lock timeout; and HTTP stock adjustment, replay, stale
recount rejection, tenant authorization, and ledger/balance consistency. This is
not load testing or proof of all concurrent business operations.

Remove the disposable Compose database when finished:

```bash
docker compose -p koradesk-foundation -f compose.test.yml down -v
```

## Update dependencies

Install the lock generator with `python -m pip install uv==0.8.16`. Edit
`requirements.in` or `requirements-dev.in`, then regenerate both files in order:

```bash
uv pip compile requirements.in --python-version 3.13 --universal --generate-hashes --no-header -o requirements.txt
uv pip compile requirements-dev.in --python-version 3.13 --universal --generate-hashes --no-header -o requirements-dev.txt
uv pip sync --python .venv --require-hashes requirements-dev.txt
```

The development resolution is constrained by the runtime lock so production and
test versions agree. Existing pins are retained when still valid. Use
`--upgrade-package PACKAGE` on the relevant compile command for a deliberate
upgrade, or `--upgrade` for a full refresh. Regenerate the development lock after
any runtime change. Review both diffs, run the full suite and audit, and commit
the input and generated files together. See the [uv locking documentation](https://docs.astral.sh/uv/pip/compile/).

The initial foundation update upgrades FastAPI/Starlette, python-multipart and
pytest to address findings from pip-audit. Other direct runtime pins are retained.
Audits query the current advisory database and fail on known vulnerabilities or
service errors; there are no ignored advisories. A clean audit is a point-in-time
result, not a guarantee of no vulnerabilities.

## Configuration validation

`app.config.Settings` validates environment and `.env` values at startup:

- `ENV` must be `dev`, `prod`, or `production`.
- `DATABASE_URL` must use `postgresql+psycopg` with host/database, or a local
  `sqlite` database for development. Explicit database ports must be valid.
- Production requires PostgreSQL and non-placeholder `APP_SECRET` and
  `VERIFY_TOKEN` values of at least 32 characters. Generate independent random
  values; length validation does not establish entropy.
- `DAILY_SUMMARY_HOUR` is 0–23, `RETENTION_MONTHS` is positive, `SMTP_PORT` is
  1–65535, and cost inputs must be finite and nonnegative.
- Legacy `SMTP_USER` and `SMTP_PASS` must be supplied together.

Development defaults remain usable by the preview and tests. Validation errors
hide input values. WhatsApp credentials must still be supplied when enabling
the legacy integration; merchant-only deployments do not require them.
Merchant `COMMERCE_*` mail settings retain their existing process-environment
validation in `commerce_mail.configuration()` and remain separate from legacy
SMTP settings.

## GitHub Actions

Pull requests against main, pushes to main/foundation, manual runs, and the weekly
schedule run lint/format and lock consistency checks, the fast test suite,
PostgreSQL 16/17 integration jobs, and a dependency audit. Jobs have read-only
repository permissions and bounded timeouts; action references are pinned to
commit SHAs. Dependabot checks those action pins weekly. Python dependencies are
updated through the reviewed lock regeneration procedure above.

The workflow adds status checks but does not change branch protection. Repository
administrators can require the checks through GitHub settings after they run.
