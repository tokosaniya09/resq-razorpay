# ResQ-Pay — one-command workflows.
.PHONY: help dev backend frontend seed demo baseline test lint format install

help:
	@echo "make install   - install backend + frontend deps"
	@echo "make dev       - run backend (:8000) and frontend (:5173)"
	@echo "make backend   - run FastAPI backend only"
	@echo "make frontend  - run the React dashboard only"
	@echo "make demo      - stream a synthetic outage into a running backend"
	@echo "make baseline  - print the naive-vs-ResQ comparison (§9)"
	@echo "make test      - run the backend test suite"
	@echo "make lint      - ruff + black --check"

install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."

seed:
	cd backend && python scripts/generate_events.py --count 40 --rate 6

demo:
	cd backend && python scripts/generate_events.py --count 90 --rate 5 --outage --outage-at 30 --outage-len 25 --seed 7

baseline:
	cd backend && python scripts/run_baseline.py --count 200 --outage --seed 7

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check app && black --check app

format:
	cd backend && ruff check --fix app && black app
