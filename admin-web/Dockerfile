ARG NODE_IMAGE=node:22-slim
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS builder

ARG NPM_REGISTRY=https://registry.npmjs.org

# 限制构建期 Node 堆上限，避免 2C2G 云服务器打包触发 OOM
ENV NODE_OPTIONS="--max-old-space-size=1024"

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci --prefer-offline --no-audit --no-fund

COPY . .
RUN npm run build \
    && find /app/dist -type f \( -name "*.js" -o -name "*.css" -o -name "*.svg" -o -name "*.html" \) -size +1k -exec sh -c 'for f do gzip -9 -c "$f" > "$f.gz"; done' _ {} +

FROM ${NGINX_IMAGE}

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
