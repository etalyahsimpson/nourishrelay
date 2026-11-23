# NourishRelay web image — Node 22 LTS, npm ci with checked-in lockfile.
FROM node:22-bookworm-slim AS builder

# NEXT_PUBLIC_* values are baked into the client bundle at build time.
# Default `/api/v1` keeps all browser traffic same-origin via the app's
# built-in API proxy (see src/app/api/v1/[...path]/route.ts).
ARG NEXT_PUBLIC_API_URL=/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
