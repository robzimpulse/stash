# Local Compose Source Build Design

## Purpose

Local self-hosting should be able to build Stash services from the current checkout instead of pulling published GHCR images. Production self-hosting should keep using the pinned images in `docker-compose.prod.yml`.

## Chosen Approach

Use `docker-compose.local.yml` as the source-build override. This keeps `docker-compose.prod.yml` stable for third-party self-hosters while giving local users a direct build path:

```sh
docker compose -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

## Compose Changes

`docker-compose.prod.yml` remains image-based.

`docker-compose.local.yml` adds build configuration for the Stash-owned services:

- `backend`: build from repository root with `backend/Dockerfile`.
- `worker`: build from the same backend Dockerfile because it runs Celery from the backend image.
- `beat`: build from the same backend Dockerfile because it runs Celery beat from the backend image.
- `frontend`: build from `./frontend` with `frontend/Dockerfile` and pass `BACKEND_INTERNAL_URL=http://backend:3456` at build time.
- `collab`: build from `./collab` with `collab/Dockerfile`.

Infrastructure services stay image-based:

- `postgres`
- `redis`
- `caddy`

## Error Handling

Docker Compose should fail normally when a build context, Dockerfile, dependency install, or image build fails. The compose files should not add alternate image fallbacks because local source builds are the intended single path when the local override is used.

## Testing

Run:

```sh
docker compose -f docker-compose.prod.yml -f docker-compose.local.yml config
```

This verifies that the merged compose configuration is valid and that the build blocks land on the intended services. Full image builds are not required for this change because they are slower and depend on package registry/network availability.
