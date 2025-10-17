# 在线邮箱客户端服务

一个基于 FastAPI + Layui 开发的多用户在线邮箱客户端服务，支持多邮箱账户管理、实时邮件同步、邮件收发等功能。

## 主要功能

### 用户管理
- 用户注册、登录、登出
- 用户信息管理（修改个人信息、密码重置）
- 用户列表展示与搜索
- 用户注册开关控制

### 邮箱管理
- 多邮箱账户绑定与管理
- 支持 IMAP/POP3/SMTP 协议配置
- 邮箱账户授权管理
- 邮箱同步状态查看
- 邮箱账户的增删改查

### 邮件功能
- 历史邮件获取与分页展示
- 按时间、发件人、主题等条件过滤邮件
- 支持多文件夹（收件箱、发件箱、草稿箱、已删除等）
- 实时邮件推送（WebSocket）
- 邮件搜索（按关键词、发件人、收件人、日期等）
- 邮件附件查看与下载

### 邮件发送
- 邮件撰写与发送
- 支持附件上传
- 草稿邮件保存与继续编辑
- 邮件发送状态跟踪

## 技术栈

### 后端
- **框架**: FastAPI + Uvicorn
- **数据库**: SQLite
- **邮件协议**: IMAP, POP3, SMTP
- **实时通信**: WebSocket

### 前端
- **UI框架**: Layui
- **通信**: RESTful API
- **实时更新**: WebSocket

## 快速开始

### 本地运行

1. 克隆项目
```bash
git clone https://github.com/eryunser/usermails.git
cd usermails
```

2. 安装依赖
```bash
pip install -r api/requirements.txt
```

3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，配置必要的环境变量
```

4. 初始化数据库
```bash
python api/utils/init_db.py
```

5. 启动后端服务
```bash
python start_server.py
```
后端服务将运行在 `http://localhost:9999`

6. 访问前端
打开浏览器访问 `web/index.html` 或使用 Web 服务器托管 web 目录

### Docker 部署

详细的 Docker 部署说明请参考 [Docker 部署文档](./docs/DOCKER_DEPLOY.md)

## 项目结构

```
usermails-py/
├── api/                    # 后端代码
│   ├── controller/         # 控制器层
│   ├── domain/             # 业务逻辑层
│   ├── model/              # 数据库模型
│   ├── repo/               # 数据访问层
│   ├── schemas/            # 数据结构与校验
│   ├── service/            # 外部服务交互层
│   ├── utils/              # 工具函数
│   ├── runtime/            # 运行时数据
│   │   ├── logs/           # 日志文件
│   │   ├── cache/          # 缓存文件
│   │   └── files/          # 临时文件
│   └── main.py             # 入口文件
├── web/                    # 前端代码
│   ├── css/                # 样式文件
│   ├── js/                 # JavaScript 文件
│   ├── layui/              # Layui 框架
│   └── *.html              # HTML 页面
├── data/                   # 数据目录（被 .gitignore 忽略）
│   ├── datebase/           # 数据库文件
│   ├── emails/             # 邮件文件存储
│   ├── logs/               # 日志
│   └── uploads/            # 用户上传文件
├── .env                    # 环境变量（被 .gitignore 忽略）
├── .env.example            # 环境变量示例
├── docker-compose.yml      # Docker Compose 配置
└── README.md               # 项目说明
```

## API 接口

所有后端接口使用 RESTful API 风格，接口前缀为 `/api`

主要接口模块：
- `/api/auth` - 认证相关（登录、注册、登出）
- `/api/users` - 用户管理
- `/api/email-accounts` - 邮箱账户管理
- `/api/emails` - 邮件管理
- `/api/drafts` - 草稿管理
- `/api/ws` - WebSocket 连接

详细 API 文档可访问: `http://localhost:9999/docs`

## 配置说明

### 支持的邮件服务器

项目支持标准的 IMAP/POP3/SMTP 协议，可配置任何支持这些协议的邮箱服务器。

以阿里云企业邮箱为例：
- IMAP: imap.qiye.aliyun.com (端口 143/993)
- SMTP: smtp.qiye.aliyun.com (端口 25/465)

### 环境变量

主要环境变量配置请参考 `.env.example` 文件

## 开发说明

### 数据库操作
因为使用 SQLite 数据库，请使用临时脚本文件操作数据库，而不是直接删除数据库文件。

### 日志
日志文件按天存储在 `api/runtime/logs/` 目录下。

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题或建议，请通过 GitHub Issues 联系。
