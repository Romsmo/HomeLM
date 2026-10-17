# Claude-Brücke: Claude-Code-CLI hinter einem winzigen HTTP-Dienst (siehe docs/claude.md).
# Die Version ist festgenagelt: neue CLI-Versionen können Flags ändern. Zum Aktualisieren
# CLAUDE_CODE_VERSION erhöhen, neu bauen und die Tests (npm test, selftest) laufen lassen.
FROM node:22-slim
ARG CLAUDE_CODE_VERSION=2.1.302
ENV NODE_ENV=production \
    DISABLE_AUTOUPDATER=1 \
    HOME=/tmp/home \
    PORT=8099 \
    MEMORY_DIR=/memory
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && claude --version
WORKDIR /app
COPY package.json server.mjs ./
USER node
EXPOSE 8099
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD node -e "fetch('http://127.0.0.1:8099/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
