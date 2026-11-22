# syntax=docker/dockerfile:1

# ---------- deps: install exactly what package-lock.json records ----------
FROM node:24.22.2-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---------- dev: Vite dev server, code is bind-mounted ----------
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---------- build: production bundle ----------
FROM deps AS build
COPY . .
RUN npm run build

# ---------- demo: static files served by nginx, /api proxied to backend ----------
FROM nginx:1.30.6-alpine AS demo
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
