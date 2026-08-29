.PHONY: up down logs sandbox-build

up: sandbox-build
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f sglang

sandbox-build:
	docker build -t sandbox-excel:latest ./sandbox_runner