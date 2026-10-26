# FoundryOS AI web client: build with Node, serve with Caddy (HTTPS + API proxy).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
# Baked into the static bundle at build time (public values only, never secrets).
ARG VITE_API_BASE_URL
ARG VITE_DEMO_PASSWORD=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_DEMO_PASSWORD=${VITE_DEMO_PASSWORD}
RUN npm run build

FROM caddy:2.8-alpine
COPY --from=build /app/dist /srv
