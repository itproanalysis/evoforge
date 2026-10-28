# syntax=docker/dockerfile:1
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* pnpm-lock.yaml* ./
# Pin npm to the version the lockfile was generated with (npm 11):
# the stock npm 10 in node:20-slim resolves one transitive pin differently
# (@swc/helpers) and fails `npm ci` on an otherwise consistent tree.
RUN npm install -g npm@11.12.1 && if [ -f pnpm-lock.yaml ]; then npm install -g pnpm && pnpm install --frozen-lockfile; elif [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . ./
ARG NEXT_PUBLIC_API_BASE=""
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN if [ -f pnpm-lock.yaml ]; then pnpm build; else npm run build; fi

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
COPY --from=builder /app/messages ./messages
EXPOSE 3000
CMD ["node", "server.js"]
