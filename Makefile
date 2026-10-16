.PHONY: install seed api worker web test lint eval up down

install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
	cd frontend && npm install

seed:
	cd backend && python -m app.cli seed

api:
	cd backend && python -m app.cli serve --reload

worker:
	cd backend && celery -A app.workers.celery_app:celery_app worker -Q workflows -l info

web:
	cd frontend && npm run dev

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check app tests
	cd frontend && npm run lint

eval:
	cd backend && python -m app.cli evaluate

up:
	docker compose up --build

down:
	docker compose down -v
