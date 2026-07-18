FROM node:20-slim AS build
WORKDIR /app

COPY services/notifications/package.json services/notifications/package-lock.json* ./
RUN npm install

COPY services/notifications/ .
COPY proto/notifications.proto ./proto/notifications.proto

RUN npx prisma generate
RUN npx tsc

FROM node:20-slim
WORKDIR /app

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/proto ./proto
COPY --from=build /app/prisma ./prisma
COPY --from=build /app/package.json ./package.json

CMD ["sh", "-c", "npx prisma migrate deploy && node dist/src/main.js"]
