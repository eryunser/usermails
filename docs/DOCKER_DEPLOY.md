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

编辑 `.env` 文件，配置必要的参数。

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

## 数据持久化

项目使用以下目录进行数据持久化：

- `./data` - 数据库、邮件文件、上传文件
- `./api/runtime` - 日志、缓存、临时文件

这些目录通过 Docker 卷挂载到宿主机，确保数据不会因容器重启而丢失。

### 备份数据

```bash
# 备份数据目录
tar -czf usermails-backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf usermails-backup-YYYYMMDD.tar.gz
```

## 更新服务

```bash
# 拉取最新代码
git pull origin main

# 重新构建并启动
docker-compose up -d --build

# 清理旧镜像
docker image prune -f
```

## 故障排查

### 查看容器日志

```bash
docker-compose logs api
```

### 检查端口占用

```bash
# Linux/Mac
netstat -tulpn | grep 9999

# Windows
netstat -ano | findstr 9999
```

### 检查环境变量配置

```bash
docker-compose config
```

## 技术支持

如遇到问题，请：
- 查看项目 [README](../README.md)
- 提交 [GitHub Issue](https://github.com/eryunser/usermails/issues)
- 查看 Docker 日志进行故障排查
