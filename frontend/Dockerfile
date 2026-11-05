FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build
FROM nginx:1.27-alpine
# /api/ 를 관제탑으로 전달하는 설정(켜질 때 TOWER_URL 을 채움)
ENV TOWER_URL=http://host.docker.internal:8100
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
