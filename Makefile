# Local self-host: speed up container up/down. Compose-only — the bare-metal
# dev stack (./start.sh) is a separate workflow.
COMPOSE = docker compose -f docker-compose.prod.yml -f docker-compose.local.yml

.PHONY: up down build logs ps restart

# Start/recreate containers (reuses images — rebuild separately with `make build`).
up:
	$(COMPOSE) up -d

# Stop containers (keeps volumes).
down:
	$(COMPOSE) down

# Rebuild images after a Dockerfile change; `make build up` rebuilds then starts.
build:
	$(COMPOSE) build

# Tail all service logs.
logs:
	$(COMPOSE) logs -f

# Container status.
ps:
	$(COMPOSE) ps

# Restart the stack.
restart:
	$(COMPOSE) restart
