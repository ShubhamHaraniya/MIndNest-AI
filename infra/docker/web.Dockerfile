FROM node:25-alpine

RUN corepack enable
WORKDIR /app

# Install dependencies first so Docker can cache this layer.
# No lockfile is committed yet, so installs are not frozen; commit pnpm-lock.yaml and switch
# to --frozen-lockfile once it exists.
COPY package.json pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --no-frozen-lockfile

COPY apps/web apps/web
WORKDIR /app/apps/web
# Next.js bakes rewrite destinations in at build time, so the API address inside the compose
# network must be set before `pnpm build`.
ENV API_INTERNAL_URL=http://api:8000
RUN pnpm build

ENV NODE_ENV=production
EXPOSE 3000
CMD ["pnpm", "exec", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
