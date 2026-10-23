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

# Rebuild local images from this checkout (the docker-compose.local.yml override
# builds from ./backend/Dockerfile instead of pulling GHCR) and recreate the
# containers whose image changed.
#
# SIGNPOST: `up`/`down` only (re)start the pulled GHCR image — they never apply
# this branch's Dockerfile changes. After merging main into personal, run
# `make build` if this branch carries image-level changes main lacks (e.g. the
# claude + stashai install in backend/Dockerfile that local-mode /agents needs);
# `make up` alone will silently keep running the old image and the agent turn
# fails with "The agent turn failed. Try again." (FileNotFoundError: 'claude').
build:
	$(COMPOSE) up -d --build

# Tail all service logs.
logs:
	$(COMPOSE) logs -f

# Container status.
ps:
	$(COMPOSE) ps

# Restart the stack.
restart:
	$(COMPOSE) restart
