.PHONY: help schema psql extract diff alerts publish pipeline test api web dev web-install web-build dbt-debug dbt-run dbt-test dbt-docs check-setup

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
	@echo "  pipeline      run extract -> diff -> alerts -> publish"
	@echo "  api           run FastAPI locally on :8551 with auto-reload"
	@echo "  web           run Vite dev server on :5551 (proxies /api → :8551)"
	@echo "  dev           run api + web together (you'll need two terminals)"
	@echo "  web-install   install npm deps under web/"
	@echo "  web-build     production build of the React app"
	@echo "  test          run pytest unit tests"
	@echo "  dbt-debug     verify dbt connects to Neon (Phase 2)"
	@echo "  dbt-run       run all dbt models (Phase 2)"
	@echo "  dbt-test      run all dbt tests (Phase 2)"
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

pipeline: extract diff alerts publish

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

dbt-run:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt run

dbt-test:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt test

dbt-docs:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt docs generate && DBT_PROFILES_DIR=. dbt docs serve
