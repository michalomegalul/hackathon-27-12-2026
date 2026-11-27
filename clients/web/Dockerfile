# The `web` service: nginx with the React site built in (served at /, see nginx.conf).
# Build context is the repo root (compose.yaml): the site imports examples/*.yaml with ?raw.
FROM node:24-slim AS build
WORKDIR /src/clients/web
COPY clients/web/package.json clients/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY clients/web ./
COPY examples /src/examples
RUN npm run build

FROM nginx:alpine
COPY --from=build /src/clients/web/dist /usr/share/nginx/web
