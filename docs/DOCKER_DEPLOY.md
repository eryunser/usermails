# Docker 部署文档

本文档介绍如何使用 Docker 和 Docker Compose 部署在线邮箱客户端服务。

## 前置要求

- Docker (版本 20.10 或更高)
- Docker Compose (版本 2.0 或更高)

## 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/eryunser/usermails.git
cd usermails
```

### 2. 配置环境变量

复制环境变量示例文件并根据实际情况修改：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下主要参数：

```env
# 数据库配置
DATABASE_URL=sqlite:///./data/datebase/usermails.db

# JWT 配置
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 服务端口
API_PORT=9999
WEB_PORT=80

# 其他配置...
```

### 3. 使用 Docker Compose 启动服务

```bash
docker-compose up -d
```

这将启动以下服务：
- **后端服务**: 运行在 `http://localhost:9999`
- **前端服务**: 运行在 `http://localhost:80` (或配置的端口)

### 4. 查看服务状态

```bash
# 查看运行中的容器
docker-compose ps

# 查看日志
docker-compose logs -f

# 查看特定服务的日志
docker-compose logs -f api
docker-compose logs -f web
```

### 5. 停止服务

```bash
# 停止服务
docker-compose stop

# 停止并删除容器
docker-compose down

# 停止并删除容器、网络、卷
docker-compose down -v
```

## 手动构建镜像

如果需要手动构建 Docker 镜像：

### 构建后端镜像

```bash
cd api
docker build -t usermails-api:latest .
```

### 构建前端镜像

```bash
cd web
docker build -t usermails-web:latest .
```

### 运行容器

```bash
# 创建网络
docker network create usermails-network

# 运行后端容器
docker run -d \
  --name usermails-api \
  --network usermails-network \
  -p 9999:9999 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/.env:/app/.env \
  usermails-api:latest

# 运行前端容器
docker run -d \
  --name usermails-web \
  --network usermails-network \
  -p 80:80 \
  usermails-web:latest
```

## Docker Compose 配置说明

项目根目录的 `docker-compose.yml` 文件配置了完整的服务编排：

```yaml
version: '3.8'

services:
  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    container_name: usermails-api
    ports:
      - "${API_PORT:-9999}:9999"
    volumes:
      - ./data:/app/data
      - ./api/runtime:/app/runtime
    env_file:
      - .env
    restart: unless-stopped
    networks:
      - usermails-network

  web:
    build:
      context: ./web
      dockerfile: Dockerfile
    container_name: usermails-web
    ports:
      - "${WEB_PORT:-80}:80"
    depends_on:
      - api
    restart: unless-stopped
    networks:
      - usermails-network

networks:
  usermails-network:
    driver: bridge

volumes:
  data:
```

## 数据持久化

### 数据卷挂载

项目使用以下目录进行数据持久化：

- `./data` - 数据库、邮件文件、上传文件
- `./api/runtime` - 日志、缓存、临时文件

这些目录通过 Docker 卷挂载到宿主机，确保数据不会因容器重启而丢失。

### 备份数据

```bash
# 备份数据目录
tar -czf usermails-backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf usermails-backup-20250117.tar.gz
```

## 生产环境部署建议

### 1. 使用反向代理

建议使用 Nginx 作为反向代理，配置 SSL 证书：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # 前端
    location / {
        proxy_pass http://localhost:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 后端 API
    location /api {
        proxy_pass http://localhost:9999;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /api/ws {
        proxy_pass http://localhost:9999;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. 环境变量配置

生产环境建议修改以下配置：

```env
# 使用强密码
SECRET_KEY=use-a-very-strong-random-secret-key

# 调整 Token 过期时间
ACCESS_TOKEN_EXPIRE_MINUTES=60

# 生产模式
DEBUG=false

# 日志级别
LOG_LEVEL=INFO
```

### 3. 资源限制

在 `docker-compose.yml` 中添加资源限制：

```yaml
services:
  api:
    # ...
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

### 4. 健康检查

添加健康检查配置：

```yaml
services:
  api:
    # ...
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9999/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### 5. 日志管理

配置日志驱动和轮转：

```yaml
services:
  api:
    # ...
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## 更新和维护

### 更新服务

```bash
# 拉取最新代码
git pull origin main

# 重新构建并启动
docker-compose up -d --build

# 清理旧镜像
docker image prune -f
```

### 查看资源使用情况

```bash
# 查看容器资源使用
docker stats

# 查看磁盘使用
docker system df
```

### 清理未使用的资源

```bash
# 清理停止的容器
docker container prune -f

# 清理未使用的镜像
docker image prune -a -f

# 清理未使用的卷
docker volume prune -f

# 清理所有未使用的资源
docker system prune -a -f
```

## 故障排查

### 容器无法启动

1. 查看容器日志：
```bash
docker-compose logs api
```

2. 检查端口占用：
```bash
netstat -tulpn | grep 9999
```

3. 检查环境变量配置：
```bash
docker-compose config
```

### 数据库连接失败

1. 确保数据目录权限正确：
```bash
chmod -R 755 data/
```

2. 检查数据库文件是否存在：
```bash
ls -la data/datebase/
```

### WebSocket 连接失败

1. 检查防火墙设置
2. 确认反向代理配置正确
3. 查看浏览器控制台错误信息

## 监控和日志

### 日志查看

```bash
# 实时查看所有日志
docker-compose logs -f

# 查看最近 100 行日志
docker-compose logs --tail=100

# 查看特定时间范围的日志
docker-compose logs --since 2025-01-17T10:00:00
```

### 监控工具推荐

- **Portainer**: Docker 容器管理界面
- **Prometheus + Grafana**: 性能监控
- **ELK Stack**: 日志收集和分析

## 安全建议

1. **定期更新**: 保持 Docker 和镜像版本最新
2. **最小权限**: 容器使用非 root 用户运行
3. **网络隔离**: 使用 Docker 网络隔离服务
4. **敏感信息**: 使用 Docker Secrets 管理敏感配置
5. **镜像扫描**: 定期扫描镜像安全漏洞

```bash
# 使用 Docker Scout 扫描镜像
docker scout cves usermails-api:latest
```

## 参考链接

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [FastAPI 部署指南](https://fastapi.tiangolo.com/deployment/)

## 技术支持

如遇到问题，请通过以下方式获取帮助：

- 查看项目 [README](../README.md)
- 提交 [GitHub Issue](https://github.com/eryunser/usermails/issues)
- 查看 Docker 日志进行故障排查
