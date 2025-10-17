# 前端静态文件镜像
FROM nginx:alpine

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/nginx.conf

# 复制前端文件
COPY . /usr/share/nginx/html/

# 创建上传目录
RUN mkdir -p /usr/share/nginx/html/uploads/avatars \
    && mkdir -p /usr/share/nginx/html/uploads/images

# 暴露端口
EXPOSE 80

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]
