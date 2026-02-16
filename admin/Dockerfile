# =============================================================================
# LITTLE NATE — Admin Console (React)
# Multi-stage: build static assets, then serve with lightweight server
# =============================================================================

# ─── Stage 1: Build ──────────────────────────────────────────────────────────
FROM node:22-alpine AS build

WORKDIR /app

# Copy package files and install deps
COPY package*.json ./
RUN npm install

# Copy source and build
COPY . .
RUN npm run build

# ─── Stage 2: Serve ──────────────────────────────────────────────────────────
FROM node:22-alpine

WORKDIR /app

# Install serve for static file hosting
RUN npm install -g serve@14

# Copy built assets from build stage
COPY --from=build /app/build ./build

EXPOSE 3000

# Serve the production build on port 3000
CMD ["serve", "-s", "build", "-l", "3000"]
