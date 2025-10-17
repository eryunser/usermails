// API请求模块
const Api = {
    // API配置
    config: {
        apiBaseUrl: location.origin + '/api',
    },

    // 当前用户缓存
    _currentUserCache: null,
    
    // 从 localStorage 加载用户缓存
    _loadUserFromStorage: function() {
        try {
            const userStr = localStorage.getItem('current_user');
            if (userStr) {
                this._currentUserCache = JSON.parse(userStr);
            }
        } catch (e) {
            console.error('加载用户缓存失败:', e);
            localStorage.removeItem('current_user');
        }
    },

    // API请求封装
    apiRequest: function(endpoint, options = {}) {
        const url = this.config.apiBaseUrl + endpoint;
        const token = localStorage.getItem('token'); // 每次请求时都从localStorage获取最新的token
        
        const config = {
            url: url,
            type: options.method || 'GET',
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            dataType: 'json',
            ...options
        };

        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }

        if (options.body) {
            config.data = options.body;
        }

        return new Promise((resolve, reject) => {
            $.ajax(config)
                .done((data, textStatus, jqXHR) => {
                    // 检查是否有新token（JWT自动续期）
                    try {
                        const newToken = jqXHR.getResponseHeader('X-New-Token');
                        if (newToken && newToken.trim() !== '') {
                            // 保存旧token用于调试
                            const oldToken = localStorage.getItem('token');
                            
                            // 更新token
                            localStorage.setItem('token', newToken);
                            
                            // 输出续期信息
                            console.log('%c✓ Token已自动续期', 'color: green; font-weight: bold;');
                            console.log('旧Token前10位:', oldToken ? oldToken.substring(0, 10) : 'null');
                            console.log('新Token前10位:', newToken.substring(0, 10));
                            
                            // 通知应用需要重连WebSocket
                            if (window.App && typeof window.App.reconnectWebSocket === 'function') {
                                window.App.reconnectWebSocket();
                            }
                        }
                    } catch (e) {
                        console.error('Token续期处理错误:', e);
                    }
                    
                    if (data.success === false) {
                        reject(new Error(data.msg || '操作失败'));
                    } else {
                        // 如果 success 字段不存在，或者为 true，则认为成功
                        // 如果 data 字段存在，则返回 data，否则返回整个响应
                        resolve(data.data !== undefined ? data.data : data);
                    }
                })
                .fail((jqXHR, textStatus, errorThrown) => {
                    if (jqXHR.status === 401) {
                        this.handleLogout();
                        reject(new Error('认证失败'));
                    } else {
                        const errorData = jqXHR.responseJSON;
                        const errorMessage = errorData?.detail || errorData?.msg || errorThrown;
                        console.error('API请求错误:', errorMessage);
                        reject(new Error(errorMessage));
                    }
                });
        });
    },

    // 获取当前用户信息（带缓存）
    getCurrentUser: function(forceRefresh = false) {
        // 首次加载时尝试从 localStorage 恢复缓存
        if (!this._currentUserCache && !forceRefresh) {
            this._loadUserFromStorage();
        }
        
        // 如果强制刷新或没有缓存，则重新请求
        if (forceRefresh || !this._currentUserCache) {
            return this.apiRequest('/auth/me').then(user => {
                // 缓存用户信息到内存
                this._currentUserCache = user;
                // 持久化完整用户对象到 localStorage
                localStorage.setItem('current_user', JSON.stringify(user));
                localStorage.setItem('current_user_id', user.id);
                return user;
            }).catch(err => {
                // 清除缓存
                this._currentUserCache = null;
                localStorage.removeItem('current_user');
                localStorage.removeItem('current_user_id');
                throw err;
            });
        }
        
        // 返回缓存的Promise
        return Promise.resolve(this._currentUserCache);
    },

    // 清除当前用户缓存
    clearUserCache: function() {
        this._currentUserCache = null;
        localStorage.removeItem('current_user');
        localStorage.removeItem('current_user_id');
    },

    // 处理退出登录
    handleLogout: function() {
        this.clearUserCache();
        localStorage.removeItem('token');
        window.location.href = 'login.html';
    },
};
