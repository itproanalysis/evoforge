# syntax=docker/dockerfile:1
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* pnpm-lock.yaml* ./
RUN if [ -f pnpm-lock.yaml ]; then npm install -g pnpm && pnpm install --frozen-lockfile; elif [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . ./
RUN if [ -f pnpm-lock.yaml ]; then pnpm build; else npm run build; fi

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
