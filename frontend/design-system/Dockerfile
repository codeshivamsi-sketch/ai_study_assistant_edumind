FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/design-system/package.json frontend/design-system/package-lock.json* ./
RUN npm install
COPY frontend/design-system/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/design-system/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
