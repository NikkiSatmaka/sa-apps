# ============================================
# Multi-stage Dockerfile untuk Next.js Frontend
# Target: Node 26 Alpine, image < 500MB
# ============================================

# --- Stage 1: Dependencies ---
FROM node:26-alpine AS deps

WORKDIR /app

# Install pnpm 12 secara eksplisit & ter-pin (tanpa corepack — selaras dengan mise)
RUN npm i -g pnpm@12

# Install dependencies dari pnpm-lock.yaml (frozen agar reproducible)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- Stage 2: Builder ---
FROM node:26-alpine AS builder

WORKDIR /app

# Install pnpm 12 secara eksplisit & ter-pin (tanpa corepack — selaras dengan mise)
RUN npm i -g pnpm@12

# Copy dependencies dari stage sebelumnya
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build argument untuk API URL (tersedia saat build time)
ARG NEXT_PUBLIC_API_URL=/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Disable telemetry saat build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application
RUN pnpm run build

# --- Stage 3: Runtime ---
FROM node:26-alpine AS runtime

WORKDIR /app

# Buat user non-root untuk keamanan
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy hanya file yang diperlukan untuk production.
# --chown wajib: runtime berjalan sebagai user non-root `nextjs`; tanpa ini
# public/ ter-copy sebagai root dan Next standalone server gagal baca (EACCES).
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Gunakan user non-root
USER nextjs

# Expose port frontend
EXPOSE 3000

# Environment variables runtime
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV NEXT_TELEMETRY_DISABLED=1

# Healthcheck lewat route /api/health (tidak bergantung pada backend).
# wget bawaan BusyBox alpine; 127.0.0.1 (bukan localhost) menghindari resolve ke ::1.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD wget -q --spider http://127.0.0.1:3000/api/health || exit 1

# Jalankan Next.js standalone server
CMD ["node", "server.js"]
