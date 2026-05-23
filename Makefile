.PHONY: help schema psql extract diff alerts publish resolve-citations pipeline test api web dev web-install web-build dbt-debug dbt-snapshot dbt-run dbt-test dbt-build dbt-docs check-setup

ifneq (,$(wildcard .env))
    include .env
    export
endif

DBT_DIR := etl/transform

help:
	@echo "Targets:"
	@echo "  check-setup   verify Neon + R2 connectivity and Phase 1 schema"
	@echo "  schema        apply etl/schema.sql to \$$DATABASE_URL (idempotent)"
	@echo "  psql          open an interactive psql session against \$$DATABASE_URL"
	@echo "  extract       pull CNEOS+SBDB, upload raw to R2, UPSERT into Postgres, update MANIFEST"
	@echo "  diff          compute approach_events between latest two snapshots"
	@echo "  alerts        evaluate threshold rules against the latest events → alerts table"
	@echo "  publish       generate public/{upcoming,noteworthy}.{rss,json} + public/health.json"
	@echo "  resolve-citations  fetch MPECs referenced in discovery_attributions, build citation graph"
	@echo "  pipeline      run extract -> diff -> alerts -> dbt (snapshot+run) -> publish"
	@echo "  api           run FastAPI locally on :8551 with auto-reload"
	@echo "  web           run Vite dev server on :5551 (proxies /api → :8551)"
	@echo "  dev           run api + web together (you'll need two terminals)"
	@echo "  web-install   install npm deps under web/"
	@echo "  web-build     production build of the React app"
	@echo "  test          run pytest unit tests"
	@echo "  dbt-debug     verify dbt connects to Neon (Phase 2)"
	@echo "  dbt-snapshot  refresh SCD-2 snapshots (dim_object history)"
	@echo "  dbt-run       run all dbt models (staging views + marts)"
	@echo "  dbt-test      run all dbt tests"
	@echo "  dbt-build     snapshot -> run -> test (the full Phase 2 refresh)"
	@echo "  dbt-docs      generate and serve dbt docs locally (Phase 2)"

check-setup:
	python -m etl.check_setup

schema:
	psql "$$DATABASE_URL" -f etl/schema.sql

psql:
	psql "$$DATABASE_URL"

extract:
	python -m etl.extract

diff:
	python -m etl.diff

alerts:
	python -m etl.alerts

publish:
	python -m etl.publish

resolve-citations:
	python -m etl.resolve_citations

# dbt (snapshot+run) sits before publish because publish + the API read from
# the marts — skipping it leaves new objects 404ing on their detail pages.
# dbt-test is intentionally omitted so a data-quality failure can't block
# publishing already-built marts (run `make dbt-test` or `make dbt-build`).
pipeline: extract diff alerts dbt-snapshot dbt-run publish

api:
	uvicorn api.index:app --reload --port 8551

web-install:
	cd web && npm install

web:
	cd web && npm run dev

web-build:
	cd web && npm run build

dev:
	@echo "Run 'make api' in one terminal and 'make web' in another."

test:
	pytest -v

dbt-debug:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt debug

dbt-snapshot:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt snapshot

dbt-run:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt run

dbt-test:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt test

dbt-build: dbt-snapshot dbt-run dbt-test

dbt-docs:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt docs generate && DBT_PROFILES_DIR=. dbt docs serve
