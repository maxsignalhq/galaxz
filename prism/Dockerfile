# Prism operator UI — multi-stage: build the Vite bundle, serve it with nginx.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# nginx:alpine runs envsubst over /etc/nginx/templates/*.template on startup,
# writing the result to /etc/nginx/conf.d/. API_TARGET / GALAXZ_API_KEY come from
# the compose environment.
ENV API_TARGET=http://galaxz:8001
ENV GALAXZ_API_KEY=""
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
