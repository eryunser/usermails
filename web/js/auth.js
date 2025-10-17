// 认证模块 - 用于 login.html
const AuthModule = {
    // 检查Token并自动登录
    checkTokenAndRedirect: async function() {
        const token = localStorage.getItem('token');
        if (!token) {
            return; // 没有token，停留在登录页
        }
        
        try {
            // 优先使用缓存的用户信息
            const cachedUser = localStorage.getItem('current_user');
            if (cachedUser) {
                // 有缓存，尝试静默验证token有效性
                try {
                    await Api.getCurrentUser(false); // 使用缓存，不强制刷新
                    // Token有效，直接跳转
                    window.location.href = 'index.html';
                    return;
                } catch (error) {
                    // Token可能过期，清除缓存后重试
                    console.log('缓存的token可能已过期，尝试重新验证...');
                }
            }
            
            // 没有缓存或token过期，重新请求用户信息
            await Api.getCurrentUser(true); // 强制刷新
            window.location.href = 'index.html';
            
        } catch (error) {
            // Token无效或过期，静默清除（不提示）
            Api.clearUserCache();
            localStorage.removeItem('token');
            console.log('Token验证失败，请重新登录');
        }
    },

    // 处理登录
    handleLogin: async function(fields) {
        const loginData = {
            username: fields.username,
            password: fields.password,
            mfa_token: fields.mfa_token || null
        };

        try {
            const data = await Api.apiRequest('/auth/login', {
                method: 'POST',
                body: JSON.stringify(loginData)
            });

            // 保存token
            localStorage.setItem('token', data.access_token);
            
            // 登录成功后立即获取并缓存用户信息
            try {
                await Api.getCurrentUser(true); // 强制刷新用户信息
            } catch (error) {
                console.error('获取用户信息失败:', error);
            }
            
            window.location.href = 'index.html';
            
        } catch (error) {
            if (window.layui && layui.layer) {
                layui.layer.msg(error.message || error.detail, { icon: 2 });
            } else {
                alert(error.message || error.detail);
            }
        }
    },

    // 提示输入MFA
    promptForMfa: function(fields) {
        layui.layer.prompt({
            formType: 0,
            title: '请输入MFA令牌',
            area: ['300px', '150px']
        }, (value, index, elem) => {
            layui.layer.close(index);
            fields.mfa_token = value;
            this.handleLogin(fields);
        });
    },

    // 处理注册
    handleRegister: async function(fields) {
        const userData = {
            username: fields.username,
            password: fields.password
        };

        if (userData.password !== fields.confirm_password) {
            layui.layer.msg('两次输入的密码不一致', { icon: 2 });
            return;
        }

        try {
            await Api.apiRequest('/auth/register', {
                method: 'POST',
                body: JSON.stringify(userData)
            });

            layui.layer.msg('注册成功，请登录', { icon: 1, time: 2000 }, function() {
                window.location.href = 'login.html';
            });
            
        } catch (error) {
            layui.layer.msg(error.message || error.detail, { icon: 2, time: 3000 });
        }
    }
};
