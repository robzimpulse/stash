FROM python:3.12-slim

# System deps for the Celery worker:
#   - curl: healthcheck in compose
#   - libreoffice + poppler-utils: PPTX → PDF → PNG for the Drive PPTX importer
#   - libnss3 / libnspr4 / etc.: required by Playwright Chromium
# Chromium binary itself is downloaded by `playwright install` below.
# libreoffice adds ~400 MB to the image but is the only sane PPTX
# renderer that runs in a headless container; alternatives like
# unoconv are libreoffice wrappers anyway.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libreoffice-impress libreoffice-core \
    poppler-utils \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    libfontconfig1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 stash && \
    useradd --uid 1000 --gid stash --create-home stash

# Claude Code CLI — the local-mode /agents harness. The cloud sprite boxes
# ship claude; local mode (AGENT_EXEC_MODE=local) execs it as a subprocess
# inside this container, so install it here too. Use the native tarball (no
# node needed). The `stash` user (uid 1000) runs the app, so the binary must
# be world-executable and on PATH.
ARG CLAUDE_VERSION=2.1.181
ARG TARGETARCH
RUN curl -fsSL "https://github.com/anthropics/claude-code/releases/download/v${CLAUDE_VERSION}/claude-linux-$(if [ "${TARGETARCH}" = "amd64" ]; then echo x64; else echo ${TARGETARCH}; fi).tar.gz" \
      -o /tmp/claude.tar.gz \
    && mkdir -p /opt/claude && tar -xzf /tmp/claude.tar.gz -C /opt/claude \
    && chmod +x /opt/claude/claude && ln -s /opt/claude/claude /usr/local/bin/claude \
    && rm -f /tmp/claude.tar.gz

# The stash CLI — the local-mode harness (curator included) reaches the user's
# Stash with it, and the sprite seed installs the same PyPI package on cloud
# boxes, so the image must ship it too.
RUN pip install --no-cache-dir stashai

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browser binary. Installs into /root/.cache by default; we
# redirect to a stash-readable path so the worker (running as stash)
# can launch it.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN playwright install chromium && chown -R stash:stash /opt/playwright

COPY backend/ ./backend/
COPY docs/skills/ ./docs/skills/
# The VFS model + shell, shared verbatim with the `stash vfs` CLI command.
COPY stashvfs/ ./stashvfs/
COPY backend/entrypoint.sh ./entrypoint.sh
COPY alembic.ini ./alembic.ini
# The CLI release number clients are told about (backend/cli_release.py).
COPY pyproject.toml ./pyproject.toml

RUN mkdir -p /app/.secrets && \
    chmod 700 /app/.secrets && \
    chmod +x /app/entrypoint.sh && \
    chown -R stash:stash /app
USER stash

EXPOSE 3456

ENTRYPOINT ["/app/entrypoint.sh"]
# Two workers so one request wedging its event loop (CPU-bound work, a stuck
# call) can't take the whole instance's /health down with it — a single-worker
# instance froze and was killed by Render's health check on 2026-08-19.
# Celery services override this CMD, so this only affects the web service.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "3456", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
