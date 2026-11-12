FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
# 前端只认 VITE_API_BASE（见 src/api/http.ts、src/api/modules/chat.ts）。
# 默认 /api/v1 = 同源，由 nginx.conf 把 /api/ 反代到 java-backend:8080。
ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build:only

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
