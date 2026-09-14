# --- Build stage -------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# --- Serve stage -------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Rendered by the base image's envsubst entrypoint at startup, so the API
# upstream is a deployment parameter rather than a baked-in hostname.
# Only ${BACKEND_UPSTREAM} is substituted; nginx's own $uri/$host survive.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV BACKEND_UPSTREAM=backend:8000

EXPOSE 80
