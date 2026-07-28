FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/shell/package.json frontend/shell/package-lock.json* ./
RUN npm install
COPY frontend/shell/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/shell/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
