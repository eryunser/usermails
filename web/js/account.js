// 账户相关功能模块
const AccountModule = {
    // 同步账户
    syncAccount: async function(accountId) {
        const statusCell = $(`#account-status-${accountId}`);
        const syncButton = $(`#sync-btn-${accountId}`);

        if (statusCell.length && syncButton.length) {
            statusCell.text('请求中...');
            syncButton.prop('disabled', true);
        }

        try {
            await Api.apiRequest(`/email-accounts/${accountId}/sync`, { method: 'POST' });
            layui.layer.msg('后台同步任务已开始', { icon: 1 });
            if (statusCell.length) {
                statusCell.text('同步中...');
            }
            // 简单的轮询来检查状态并刷新
            setTimeout(() => this.checkSyncStatus(accountId), 5000);
        } catch (error) {
            layui.layer.msg('同步请求失败: ' + (error.detail || error.message), { icon: 2 });
            if (statusCell.length && syncButton.length) {
                statusCell.text('失败'); // 或者恢复之前的状态
                syncButton.prop('disabled', false);
            }
        }
    },

    // 检查同步状态
    checkSyncStatus: async function(accountId) {
        try {
            const account = await Api.apiRequest(`/email-accounts/${accountId}`);
            if (account.sync_status === 'syncing') {
                // 如果仍在同步，5秒后再次检查
                setTimeout(() => this.checkSyncStatus(accountId), 5000);
            } else {
                // 同步完成或失败，刷新当前邮件列表
                layui.layer.msg('同步完成，正在刷新列表...', { icon: 1 });
                App.loadAccountFolders(); // 刷新左侧文件夹列表
                // 刷新当前邮件列表
                if (EmailModule.currentAccountId == accountId) {
                    EmailModule.loadEmailList(EmailModule.currentFolder, EmailModule.currentAccountId);
                }
            }
        } catch (error) {
            console.error('检查同步状态失败:', error);
            // 出错时停止轮询
        }
    },

    // 删除账户
    deleteAccount: async function(accountId) {
        layer.confirm('确定要删除这个邮箱账户吗？', async function(index){
            try {
                await Api.apiRequest(`/email-accounts/${accountId}`, { method: 'DELETE' });
                layui.layer.msg('账户已删除', { icon: 1 });
                App.loadAccountFolders(); // Refresh the folder list
                // Potentially clear the view if the deleted account was active
                $('#email-list-container').html('<div class="placeholder">请选择邮件</div>');
                $('#email-detail-container').html('<div class="placeholder">请选择邮件以查看详情</div>');
            } catch (error) {
                layui.layer.msg('删除失败: ' + (error.detail || error.message), { icon: 2 });
            }
            layer.close(index);
        });
    },

    // 显示账户设置菜单
    showAccountSettings: function(accountId, triggerElement) {
        layui.dropdown.render({
            elem: triggerElement,
            show: true,
            data: [
                { title: '修改配置', id: 'edit' },
                { title: '同步', id: 'sync' },
                { title: '重命名', id: 'rename' },
                { title: '创建文件夹', id: 'create_folder' },
                { title: '复制地址', id: 'copy' },
                { type: '-' },
                { title: '删除邮箱', id: 'delete' }
            ],
            click: function(data) {
                switch (data.id) {
                    case 'edit':
                        AccountModule.editAccountConfig(accountId);
                        break;
                    case 'sync':
                        AccountModule.syncAccount(accountId);
                        break;
                    case 'rename':
                        AccountModule.renameAccount(accountId);
                        break;
                    case 'create_folder':
                        AccountModule.createFolder(accountId);
                        break;
                    case 'copy':
                        AccountModule.copyEmailAddress(accountId);
                        break;
                    case 'delete':
                        AccountModule.deleteAccount(accountId);
                        break;
                }
            }
        });
    },

    // 复制邮箱地址
    copyEmailAddress: async function(accountId) {
        try {
            const account = await Api.apiRequest(`/email-accounts/${accountId}`);
            navigator.clipboard.writeText(account.email).then(() => {
                layui.layer.msg('邮箱地址已复制', { icon: 1 });
            }, () => {
                layui.layer.msg('复制失败', { icon: 2 });
            });
        } catch (error) {
            layui.layer.msg('获取邮箱地址失败', { icon: 2 });
        }
    },

    // 重命名账户
    renameAccount: async function(accountId) {
        try {
            const account = await Api.apiRequest(`/email-accounts/${accountId}`);
            layer.prompt({
                formType: 0,
                value: account.name,
                title: '重命名账户',
            }, async function(value, index){
                layer.close(index);
                // 重命名操作直接调用更新接口，不需要验证
                try {
                    await Api.apiRequest(`/email-accounts/${accountId}`, {
                        method: 'PUT',
                        body: JSON.stringify({ name: value })
                    });
                    layui.layer.msg('账户重命名成功', { icon: 1 });
                    App.loadAccountFolders();
                } catch (error) {
                    layui.layer.msg('重命名失败: ' + (error.detail || error.message), { icon: 2 });
                }
            });
        } catch (error) {
            layui.layer.msg('加载账户信息失败', { icon: 2 });
        }
    },

    // 修改账户配置
    editAccountConfig: async function(accountId) {
        try {
            const account = await Api.apiRequest(`/email-accounts/${accountId}`);
            this.showEditAccountModal(account);
        } catch (error) {
            layui.layer.msg('加载账户信息失败: ' + (error.detail || error.message), { icon: 2 });
        }
    },

    // 显示编辑账户弹窗
    showEditAccountModal: function(account) {
        const formHtml = `
            <div style="padding: 20px;">
                <form class="layui-form" id="edit-account-form" lay-filter="edit-account-form">
                    <input type="hidden" name="id" value="${account.id}">
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱名称</label>
                        <div class="layui-input-block">
                            <input type="text" name="name" required lay-verify="required" placeholder="例如：个人邮箱" class="layui-input" value="${account.name}">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱地址</label>
                        <div class="layui-input-block">
                            <input type="email" name="email" required lay-verify="required|email" placeholder="请输入邮箱地址" class="layui-input" value="${account.email}" readonly>
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱密码</label>
                        <div class="layui-input-block">
                            <input type="password" name="password" placeholder="如需修改请填写新密码" class="layui-input">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">IMAP服务器</label>
                        <div class="layui-input-block">
                            <input type="text" name="imap_server" required lay-verify="required" placeholder="如: imap.qiye.aliyun.com" class="layui-input" value="${account.imap_server}">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">IMAP端口</label>
                        <div class="layui-input-inline" style="width: 100px;">
                            <input type="number" name="imap_port" id="imap_port_edit" value="${account.imap_port}" required lay-verify="required" class="layui-input">
                        </div>
                        <div class="layui-form-mid layui-word-aux">
                            <input type="checkbox" name="imap_ssl" lay-skin="switch" lay-text="SSL|OFF" ${account.imap_ssl ? 'checked' : ''} lay-filter="imap_ssl_filter_edit">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">SMTP服务器</label>
                        <div class="layui-input-block">
                            <input type="text" name="smtp_server" required lay-verify="required" placeholder="如: smtp.qiye.aliyun.com" class="layui-input" value="${account.smtp_server}">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">SMTP端口</label>
                        <div class="layui-input-inline" style="width: 100px;">
                            <input type="number" name="smtp_port" id="smtp_port_edit" value="${account.smtp_port}" required lay-verify="required" class="layui-input">
                        </div>
                        <div class="layui-form-mid layui-word-aux">
                            <input type="checkbox" name="smtp_ssl" lay-skin="switch" lay-text="SSL|OFF" ${account.smtp_ssl ? 'checked' : ''} lay-filter="smtp_ssl_filter_edit">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <div class="layui-input-block">
                            <button class="layui-btn" lay-submit lay-filter="editAccount">保存修改</button>
                            <button type="button" class="layui-btn layui-btn-primary" onclick="layer.closeAll();">取消</button>
                        </div>
                    </div>
                </form>
            </div>
        `;

        layer.open({
            type: 1,
            title: '修改邮箱账户',
            content: formHtml,
            area: ['550px', 'auto'],
            success: function(layero, index){
                layui.form.render(null, 'edit-account-form');

                layui.form.on('switch(imap_ssl_filter_edit)', function(data){
                    $('#imap_port_edit').val(data.elem.checked ? '993' : '143');
                });

                layui.form.on('switch(smtp_ssl_filter_edit)', function(data){
                    $('#smtp_port_edit').val(data.elem.checked ? '465' : '25');
                });

                layui.form.on('submit(editAccount)', function(data){
                    AccountModule.handleUpdateAccount(account.id, data.field);
                    return false;
                });
            }
        });
    },

    // 处理更新账户
    handleUpdateAccount: async function(accountId, formData) {
        const accountData = {
            name: formData.name,
            email: formData.email, // 确保 email 字段被包含
            imap_server: formData.imap_server,
            imap_port: parseInt(formData.imap_port),
            imap_ssl: formData.imap_ssl === 'on',
            smtp_server: formData.smtp_server,
            smtp_port: parseInt(formData.smtp_port),
            smtp_ssl: formData.smtp_ssl === 'on'
        };

        // 如果用户输入了新密码，则包含密码字段
        if (formData.password) {
            accountData.password = formData.password;
        }

        try {
            // 在保存前进行验证
            await AccountModule.validateAndSave(accountData, accountId);
        } catch (error) {
            layui.layer.msg('更新失败: ' + (error.detail || error.message), { icon: 2 });
        }
    },

    // 加载添加账户页面 (弹窗形式)
    loadAddAccount: function() {
        const providers = {
            'custom': { name: '自定义' },
            'aliyun': { name: '阿里云企业邮箱', imap_server: 'imap.qiye.aliyun.com', imap_port: 993, imap_ssl: true, smtp_server: 'smtp.qiye.aliyun.com', smtp_port: 465, smtp_ssl: true },
            'microsoft': { name: 'Microsoft 365', imap_server: 'outlook.office365.com', imap_port: 993, imap_ssl: true, smtp_server: 'smtp.office365.com', smtp_port: 587, smtp_ssl: false }, // 通常使用STARTTLS，这里简化为非SSL端口
            'google': { name: 'Gmail', imap_server: 'imap.gmail.com', imap_port: 993, imap_ssl: true, smtp_server: 'smtp.gmail.com', smtp_port: 465, smtp_ssl: true },
            'hotmail': { name: 'Hotmail/Outlook', imap_server: 'outlook.office365.com', imap_port: 993, imap_ssl: true, smtp_server: 'smtp.office365.com', smtp_port: 587, smtp_ssl: false },
        };

        const formHtml = `
            <div style="padding: 20px;">
                <form class="layui-form" id="add-account-form" lay-filter="add-account-form">
                    <div class="layui-form-item">
                        <label class="layui-form-label">服务商</label>
                        <div class="layui-input-block">
                            <select name="provider" lay-filter="provider-select">
                                ${Object.keys(providers).map(key => `<option value="${key}">${providers[key].name}</option>`).join('')}
                            </select>
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱名称</label>
                        <div class="layui-input-block">
                            <input type="text" name="name" required lay-verify="required" placeholder="例如：个人邮箱" class="layui-input">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱地址</label>
                        <div class="layui-input-block">
                            <input type="email" name="email" required lay-verify="required|email" placeholder="请输入邮箱地址" class="layui-input">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱密码</label>
                        <div class="layui-input-block">
                            <input type="password" name="password" required lay-verify="required" placeholder="请输入邮箱密码" class="layui-input">
                        </div>
                    </div>
                    <div id="custom-settings">
                        <div class="layui-form-item">
                            <label class="layui-form-label">IMAP服务器</label>
                            <div class="layui-input-block">
                                <input type="text" name="imap_server" required lay-verify="required" placeholder="如: imap.qiye.aliyun.com" class="layui-input">
                            </div>
                        </div>
                        <div class="layui-form-item">
                            <label class="layui-form-label">IMAP端口</label>
                            <div class="layui-input-inline" style="width: 100px;">
                                <input type="number" name="imap_port" id="imap_port" required lay-verify="required" class="layui-input">
                            </div>
                            <div class="layui-form-mid layui-word-aux">
                                <input type="checkbox" name="imap_ssl" lay-skin="switch" lay-text="SSL|OFF" lay-filter="imap_ssl_filter">
                            </div>
                        </div>
                        <div class="layui-form-item">
                            <label class="layui-form-label">SMTP服务器</label>
                            <div class="layui-input-block">
                                <input type="text" name="smtp_server" required lay-verify="required" placeholder="如: smtp.qiye.aliyun.com" class="layui-input">
                            </div>
                        </div>
                        <div class="layui-form-item">
                            <label class="layui-form-label">SMTP端口</label>
                            <div class="layui-input-inline" style="width: 100px;">
                                <input type="number" name="smtp_port" id="smtp_port" required lay-verify="required" class="layui-input">
                            </div>
                            <div class="layui-form-mid layui-word-aux">
                                <input type="checkbox" name="smtp_ssl" lay-skin="switch" lay-text="SSL|OFF" lay-filter="smtp_ssl_filter">
                            </div>
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <div class="layui-input-block">
                            <button class="layui-btn" lay-submit lay-filter="addAccount">立即添加</button>
                            <button type="button" class="layui-btn layui-btn-primary" onclick="layer.closeAll();">取消</button>
                        </div>
                    </div>
                </form>
            </div>
        `;

        layer.open({
            type: 1,
            title: '添加邮箱账户',
            content: formHtml,
            area: ['550px', 'auto'],
            success: function(layero, index){
                const form = layui.form;
                form.render(null, 'add-account-form');

                form.on('select(provider-select)', function(data){
                    const provider = providers[data.value];
                    if (provider && data.value !== 'custom') {
                        $('input[name="imap_server"]').val(provider.imap_server);
                        $('input[name="imap_port"]').val(provider.imap_port);
                        $('input[name="imap_ssl"]').prop('checked', provider.imap_ssl);
                        $('input[name="smtp_server"]').val(provider.smtp_server);
                        $('input[name="smtp_port"]').val(provider.smtp_port);
                        $('input[name="smtp_ssl"]').prop('checked', provider.smtp_ssl);
                    }
                    $('#custom-settings').show();
                    form.render();
                });

                form.on('switch(imap_ssl_filter)', function(data){
                    $('#imap_port').val(data.elem.checked ? '993' : '143');
                });

                form.on('switch(smtp_ssl_filter)', function(data){
                    $('#smtp_port').val(data.elem.checked ? '465' : '25');
                });

                form.on('submit(addAccount)', function(data){
                    AccountModule.handleAddAccount(data.field);
                    return false;
                });
                
                // Trigger the select change to set initial state
                form.event('select(provider-select)', 'aliyun');
            }
        });
    },

    // 处理添加账户
    handleAddAccount: async function(formData) {
        const accountData = {
            name: formData.name,
            email: formData.email,
            password: formData.password,
            imap_server: formData.imap_server,
            imap_port: parseInt(formData.imap_port),
            imap_ssl: formData.imap_ssl === 'on',
            smtp_server: formData.smtp_server,
            smtp_port: parseInt(formData.smtp_port),
            smtp_ssl: formData.smtp_ssl === 'on'
        };

        try {
            // 在保存前进行验证
            await AccountModule.validateAndSave(accountData);
        } catch (error) {
            layui.layer.msg('添加失败: ' + (error.detail || error.message), { icon: 2 });
        }
    },

    // 验证并保存账户信息
    validateAndSave: async function(accountData, accountId = null) {
        const loadingIndex = layui.layer.load(1, { shade: [0.1, '#fff'] });
        try {
            // 步骤1: 隐式验证配置
            await Api.apiRequest('/email-accounts/validate', {
                method: 'POST',
                body: JSON.stringify(accountData)
            });
            
            layui.layer.close(loadingIndex);

            // 步骤2: 验证成功后，执行添加或更新操作
            const url = accountId ? `/email-accounts/${accountId}` : '/email-accounts';
            const method = accountId ? 'PUT' : 'POST';
            
            await Api.apiRequest(url, {
                method: method,
                body: JSON.stringify(accountData)
            });

            layer.closeAll();
            layui.layer.msg(accountId ? '账户更新成功' : '邮箱账户添加成功', { icon: 1 });
            App.loadAccountFolders();

        } catch (error) {
            layui.layer.close(loadingIndex);
            layui.layer.msg('验证失败: ' + (error.detail || error.message), { icon: 2 });
            // 抛出错误以便上层调用捕获
            throw error;
        }
    },

    // 加载个人资料
    loadProfile: async function() {
        try {
            const user = await App.getCurrentUser();
            this.renderProfile(user);
        } catch (error) {
            layui.layer.msg('加载用户信息失败', { icon: 2 });
        }
    },

    // 渲染个人资料
    renderProfile: function(user) {
        const mfaEnabled = user.is_mfa_enabled;
        const formHtml = `
            <div style="padding: 20px;">
                <form class="layui-form" id="profile-form" lay-filter="profile-form">
                    <div class="layui-form-item">
                        <label class="layui-form-label">头像</label>
                        <div class="layui-input-block">
                            <div class="layui-upload">
                                <button type="button" class="layui-btn" id="upload-avatar-btn">上传图片</button>
                                <div class="layui-upload-list">
                                    <img class="layui-upload-img" id="avatar-preview" src="${user.avatar || 'images/user-avatar.png'}" style="width: 100px; height: 100px; border-radius: 50%;">
                                    <p id="upload-avatar-text"></p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">全名</label>
                        <div class="layui-input-block">
                            <input type="text" name="full_name" value="${user.full_name || ''}" placeholder="选填" class="layui-input">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱</label>
                        <div class="layui-input-block">
                            <input type="email" name="email" value="${user.email || ''}" placeholder="邮箱地址" class="layui-input" required lay-verify="required|email">
                        </div>
                    </div>
                    <div class="layui-form-item">
                        <label class="layui-form-label">新密码</label>
                        <div class="layui-input-block">
                            <input type="password" name="password" id="new-password-input" placeholder="不改请留空" class="layui-input" title="8位以上">
                        </div>
                    </div>
                    ${mfaEnabled ? `
                    <div class="layui-form-item" id="mfa-input-container" style="display: none;">
                        <label class="layui-form-label">MFA代码</label>
                        <div class="layui-input-block">
                            <input type="text" name="mfa_token" placeholder="请输入6位MFA代码" class="layui-input" maxlength="6">
                        </div>
                    </div>
                    ` : ''}
                </form>
            </div>
        `;

        layer.open({
            type: 1,
            title: '个人资料',
            content: formHtml,
            area: ['500px', 'auto'],
            btn: ['保存', '取消'],
            shadeClose: true,
            btnAlign: 'c',
            yes: function(index, layero){
                const formData = layui.form.val('profile-form');
                AccountModule.handleUpdateProfile(formData);
            },
            success: function() {
                layui.form.render(null, 'profile-form');

                layui.upload.render({
                    elem: '#upload-avatar-btn',
                    url: Api.config.apiBaseUrl + '/users/me/avatar',
                    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') },
                    accept: 'images',
                    acceptMime: 'image/jpeg, image/png, image/gif',
                    size: 2048, // 2MB
                    done: function(res){
                        if(res.success){
                            $('#avatar-preview').attr('src', res.data.avatar_url);
                            // 更新顶部导航栏头像
                            $('.layui-nav-img').attr('src', res.data.avatar_url);
                        } else {
                            layui.layer.msg(res.msg || '上传失败');
                        }
                    },
                    error: function(){
                        layui.layer.msg('请求异常');
                    }
                });

                if (mfaEnabled) {
                    const passwordInput = $('#new-password-input');
                    const mfaContainer = $('#mfa-input-container');
                    passwordInput.on('input', function() {
                        if ($(this).val()) {
                            mfaContainer.show();
                        } else {
                            mfaContainer.hide();
                        }
                    });
                }
            }
        });
    },

    // 显示MFA设置弹窗
    showSetupMfaModal: function() {
        layer.prompt({
            formType: 1,
            title: '请输入当前密码以继续',
        }, async function(password, index){
            layer.close(index);
            try {
                // 验证密码
                await Api.apiRequest('/auth/verify-password', {
                    method: 'POST',
                    body: JSON.stringify({ password: password })
                });

                const mfaData = await Api.apiRequest('/users/me/mfa/generate', { method: 'POST' });
                const setupHtml = `
                    <div style="padding: 20px; text-align: center;">
                        <p>请使用您的认证应用扫描下方的二维码：</p>
                        <img src="${mfaData.qr_code}" alt="MFA QR Code" style="width: 200px; height: 200px; margin: 15px 0;">
                        <p>或者手动输入密钥：</p>
                        <code>${mfaData.secret}</code>
                        <hr>
                        <p>扫描后，请输入应用生成的6位数字代码以完成绑定：</p>
                        <div class="layui-form-item">
                            <input type="text" id="mfa-token-input" class="layui-input" placeholder="6位数字代码" maxlength="6">
                        </div>
                    </div>
                `;
                layer.open({
                    type: 1,
                    title: '绑定MFA',
                    content: setupHtml,
                    area: ['400px', 'auto'],
                    btn: ['确认绑定', '取消'],
                    yes: async function(index, layero) {
                        const token = $('#mfa-token-input').val();
                        if (!/^\d{6}$/.test(token)) {
                            layer.msg('请输入6位数字代码', { icon: 2, time: 2000 });
                            // 注意：这里不重新打开，因为二维码弹窗还在，只是提示用户输入正确
                            return;
                        }
                        try {
                            await Api.apiRequest('/users/me/mfa/enable', {
                                method: 'POST',
                                body: JSON.stringify({ token: token })
                            });
                            layer.msg('MFA绑定成功', { icon: 1 }, function() {
                                layer.closeAll();
                                App.checkAuthStatus(); // 重新加载用户信息和UI
                            });
                        } catch (error) {
                            layer.msg('绑定失败: ' + (error.message || '未知错误'), { icon: 2, time: 2000 }, function() {
                                layer.closeAll(); // 关闭所有弹窗
                                AccountModule.showSetupMfaModal(); // 从头开始
                            });
                        }
                    }
                });
            } catch (error) {
                layer.msg('密码验证失败', { icon: 2, time: 2000 }, function() {
                    AccountModule.showSetupMfaModal();
                });
            }
        });
    },

    // 显示禁用MFA弹窗
    showDisableMfaModal: function() {
        layer.prompt({
            formType: 0,
            title: '请输入MFA代码以禁用',
            maxlength: 6
        }, async function(token, index){
            if (!/^\d{6}$/.test(token)) {
                layer.close(index);
                layer.msg('请输入6位数字代码', { icon: 2, time: 2000 }, function() {
                    AccountModule.showDisableMfaModal();
                });
                return;
            }
            layer.close(index);
            try {
                await Api.apiRequest('/users/me/mfa/disable', {
                    method: 'POST',
                    body: JSON.stringify({ token: token })
                });
                layer.msg('MFA已禁用', { icon: 1 }, function() {
                    layer.closeAll();
                    App.checkAuthStatus(); // 重新加载用户信息和UI
                });
            } catch (error) {
                layer.msg('禁用失败: ' + (error.message || '未知错误'), { icon: 2, time: 2000 }, function() {
                    AccountModule.showDisableMfaModal();
                });
            }
        });
    },

    // 处理更新个人资料
    handleUpdateProfile: async function(formData) {
        const updateData = {
            full_name: formData.full_name?.trim() || '',
            email: formData.email?.trim() || ''
        };

        if (formData.password) {
            updateData.password = formData.password;
            if (App.config.currentUser.is_mfa_enabled) {
                if (!formData.mfa_token || !/^\d{6}$/.test(formData.mfa_token)) {
                    layui.layer.msg('需输入MFA代码', { icon: 7 });
                    return;
                }
                updateData.mfa_token = formData.mfa_token;
            }
        }

        this.executeProfileUpdate(updateData);
    },

    executeProfileUpdate: async function(updateData) {
        try {
            await Api.apiRequest('/users/me', {
                method: 'PUT',
                body: JSON.stringify(updateData)
            });
            layui.layer.msg('个人资料更新成功', { icon: 1 }, function() {
                layer.closeAll('page');
                // 清除用户缓存并重新获取
                Api.clearUserCache();
                // 如果密码被修改，可能需要重新登录或刷新状态
                if (updateData.password) {
                    App.checkAuthStatus();
                }
            });
        } catch (error) {
            layui.layer.msg('更新失败: ' + (error.message || '未知错误'), { icon: 2 });
        }
    },

    // 创建文件夹
    createFolder: function(accountId, parentFolder = null) {
        layer.prompt({
            formType: 0,
            title: parentFolder ? `在 "${parentFolder}" 下创建子文件夹` : '创建新文件夹',
            value: ''
        }, async function(folderName, index) {
            if (!folderName || folderName.trim() === '') {
                layer.msg('文件夹名称不能为空');
                return;
            }
            layer.close(index);

            try {
                await Api.apiRequest(`/email-accounts/${accountId}/folders`, {
                    method: 'POST',
                    body: JSON.stringify({
                        folder_name: folderName,
                        parent_folder: parentFolder
                    })
                });
                layer.msg('文件夹创建成功', { icon: 1 });
                App.loadAccountFolders(); // Refresh the entire folder list
            } catch (error) {
                layer.msg('创建文件夹失败: ' + (error.message || '未知错误'), { icon: 2 });
            }
        });
    },

    // 重命名文件夹
    renameFolder: function(accountId, folderName) {
        const parts = folderName.split('/');
        const currentName = parts[parts.length - 1];

        layer.prompt({
            formType: 0,
            title: `重命名文件夹 "${currentName}"`,
            value: currentName
        }, async function(newFolderName, index) {
            if (!newFolderName || newFolderName.trim() === '') {
                layer.msg('文件夹名称不能为空');
                return;
            }
            if (newFolderName === currentName) { // Compare with just the name part
                layer.close(index);
                return;
            }
            layer.close(index);

            const parentPath = parts.slice(0, -1).join('/');
            const newFullName = parentPath ? `${parentPath}/${newFolderName}` : newFolderName;

            try {
                await Api.apiRequest(`/email-accounts/${accountId}/folders`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        old_dir: folderName,
                        new_dir: newFullName
                    })
                });
                layer.msg('文件夹重命名成功', { icon: 1 });
                App.loadAccountFolders(); // Refresh the folder list
            } catch (error) {
                layer.msg('重命名失败: ' + (error.message || '未知错误'), { icon: 2 });
            }
        });
    }
};
