FROM node:24.19.0-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS dependencies

ENV COREPACK_HOME=/opt/corepack

RUN mkdir -p "${COREPACK_HOME}" \
    && chmod 755 "${COREPACK_HOME}" \
    && corepack enable \
    && corepack install --global pnpm@11.12.0 \
    && pnpm --version

WORKDIR /app

RUN chown node:node /app

COPY --chown=node:node package.json pnpm-lock.yaml ./

USER node

RUN pnpm install --frozen-lockfile


FROM dependencies AS application

COPY --chown=node:node index.html tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY --chown=node:node src ./src


FROM application AS build-validation

RUN pnpm build


FROM application AS development

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
