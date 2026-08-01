# Local Compose Source Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker-compose.local.yml` build Stash-owned services from the local checkout while `docker-compose.prod.yml` keeps pulling published GHCR images.

**Architecture:** `docker-compose.prod.yml` remains the base self-hosting configuration. `docker-compose.local.yml` overrides only local-hosting behavior: direct host ports, disabled Caddy, and build contexts for backend-derived, frontend, and collab services.

**Tech Stack:** Docker Compose, existing `backend/Dockerfile`, `frontend/Dockerfile`, and `collab/Dockerfile`.

---

### Task 1: Add Local Build Overrides

**Files:**
- Modify: `docker-compose.local.yml`

- [ ] **Step 1: Update the local usage comment**

Change the local usage comment to include `--build`:

```yaml
#   docker compose -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

- [ ] **Step 2: Add backend-derived build blocks**

Add the same backend build configuration to `backend`, `worker`, and `beat`:

```yaml
    build:
      context: .
      dockerfile: backend/Dockerfile
```

- [ ] **Step 3: Add frontend build block**

Add the frontend build configuration and build-time backend URL:

```yaml
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        BACKEND_INTERNAL_URL: http://backend:3456
```

- [ ] **Step 4: Add collab build block**

Add the collab build configuration:

```yaml
    build:
      context: ./collab
      dockerfile: Dockerfile
```

### Task 2: Validate Compose Merge

**Files:**
- Read: `docker-compose.prod.yml`
- Read: `docker-compose.local.yml`

- [ ] **Step 1: Render the merged compose config**

Run:

```sh
docker compose -f docker-compose.prod.yml -f docker-compose.local.yml config
```

Expected: command exits 0 and rendered services include build sections for `backend`, `worker`, `beat`, `frontend`, and `collab`.

- [ ] **Step 2: Inspect final git status**

Run:

```sh
git status --short
```

Expected: `docker-compose.local.yml` is modified, the superpowers design doc is staged as untracked/deleted from tracking, and the superpowers docs folder remains local/untracked.
