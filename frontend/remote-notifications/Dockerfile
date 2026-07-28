FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/remote-notifications/package.json frontend/remote-notifications/package-lock.json* ./
RUN npm install
COPY frontend/remote-notifications/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/remote-notifications/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
