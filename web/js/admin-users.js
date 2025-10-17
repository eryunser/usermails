layui.use(['table', 'layer', 'form'], function() {
    const table = layui.table;
    const layer = layui.layer;
    const form = layui.form;
    const $ = layui.$;
    
    // 获取当前用户信息（使用缓存）
    let currentUser = null;
    Api.getCurrentUser().then(user => {
        currentUser = user;
    }).catch(err => {
        console.error('获取当前用户信息失败:', err);
    });

    // 渲染表格
    const tableIns = table.render({
        elem: '#userTable',
        url: Api.config.apiBaseUrl + '/users/',
        toolbar: '#toolbarDemo',
        defaultToolbar: ['filter', 'exports', 'print'],
        headers: {
            'Authorization': 'Bearer ' + localStorage.getItem('token')
        },
        parseData: function(res) {
            return {
                code: res.success ? 0 : 1,
                msg: res.msg || res.message,
                count: res.count || 0,
                data: res.data || []
            };
        },
        cols: [[
            {field: 'id', title: 'ID', width: 80, sort: true},
            {field: 'avatar', title: '头像', width: 80, templet: '#avatarTpl'},
            {field: 'username', title: '用户名', width: 150},
            {field: 'full_name', title: '姓名', width: 150},
            {field: 'email', title: '邮箱', width: 200},
            {field: 'is_admin', title: '用户类型', width: 120, templet: '#userTypeTpl'},
            {field: 'is_active', title: '状态', width: 100, templet: '#statusTpl'},
            {field: 'is_mfa_enabled', title: 'MFA', width: 100, templet: '#mfaTpl'},
            {field: 'created_at', title: '创建时间', width: 180, sort: true},
            {fixed: 'right', title: '操作', width: 280, toolbar: '#actionBar'}
        ]],
        page: false  // 不分页
    });

    // 搜索表单提交
    form.on('submit(searchForm)', function(data) {
        const field = data.field;
        tableIns.reload({
            where: {
                username: field.username || undefined,
                email: field.email || undefined,
                is_active: field.is_active !== '' ? (field.is_active === 'true') : undefined
            }
        });
        return false;
    });
    
    // 重置搜索
    $('#resetSearch').on('click', function() {
        $('#searchForm')[0].reset();
        form.render('select');
        tableIns.reload({
            where: {}
        });
    });

    // 工具栏事件
    table.on('toolbar(userTable)', function(obj) {
        if (obj.event === 'add') {
            addUser();
        } else if (obj.event === 'refresh') {
            tableIns.reload();
            layer.msg('已刷新');
        }
    });

    // 行工具事件
    table.on('tool(userTable)', function(obj) {
        const data = obj.data;
        
        if (obj.event === 'edit') {
            editUser(data);
        } else if (obj.event === 'cancelMFA') {
            cancelMFA(data);
        } else if (obj.event === 'disable') {
            toggleUserStatus(data, false);
        } else if (obj.event === 'enable') {
            toggleUserStatus(data, true);
        } else if (obj.event === 'delete') {
            deleteUser(data);
        }
    });

    // 添加用户
    function addUser() {
        const addIndex = layer.open({
            type: 1,
            title: '添加用户',
            area: ['500px', 'auto'],
            btn: ['提交', '取消'],
            btnAlign: 'c',
            shadeClose: true,  // 点击遮罩层关闭
            content: `
                <form class="layui-form" style="padding: 20px;" lay-filter="addForm" id="addUserForm">
                    <div class="layui-form-item">
                        <label class="layui-form-label"><span style="color: red;">*</span> 用户名</label>
                        <div class="layui-input-block">
                            <input type="text" name="username" placeholder="3-50字符" 
                                   class="layui-input" required lay-verify="required">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label">姓名</label>
                        <div class="layui-input-block">
                            <input type="text" name="full_name" placeholder="选填" class="layui-input">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label"><span style="color: red;">*</span> 邮箱</label>
                        <div class="layui-input-block">
                            <input type="email" name="email" placeholder="邮箱地址" 
                                   class="layui-input" required lay-verify="required|email">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label"><span style="color: red;">*</span> 密码</label>
                        <div class="layui-input-block">
                            <div style="display: flex; align-items: center;">
                                <input type="text" name="password" id="addPassword" 
                                       placeholder="8位以上" class="layui-input" 
                                       required lay-verify="required"
                                       style="flex: 1; margin-right: 8px;">
                                <button type="button" class="layui-btn layui-btn-primary" id="generateAddBtn" 
                                        title="随机生成" style="padding: 0 15px;">
                                    <i class="layui-icon layui-icon-refresh"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            `,
            yes: function(index, layero) {/*  */
                // 直接提交表单
                const formData = form.val('addForm');
                const submitData = {
                    username: formData.username?.trim() || '',
                    full_name: formData.full_name?.trim() || '',
                    email: formData.email?.trim() || '',
                    password: formData.password || ''
                };
                
                // 验证必填字段
                if (!submitData.username) {
                    layer.msg('请输入用户名', { icon: 2 });
                    return false;
                }
                if (!submitData.email) {
                    layer.msg('请输入邮箱', { icon: 2 });
                    return false;
                }
                if (!submitData.password) {
                    layer.msg('请输入密码', { icon: 2 });
                    return false;
                }
                
                Api.apiRequest('/users/admin/create', {
                    method: 'POST',
                    body: JSON.stringify(submitData)
                })
                .then(res => {
                    layer.msg('创建成功', { icon: 1 });
                    layer.close(addIndex);
                    tableIns.reload();
                })
                .catch(error => {
                    layer.msg(error.message || '创建失败', { icon: 2 });
                });
                
                return false;
            },
            btn2: function(index) {
                layer.close(index);
            },
            success: function(layero, index) {
                form.render();
                
                // 随机密码按钮
                layero.find('#generateAddBtn').on('click', function() {
                    Api.apiRequest('/users/admin/generate-password')
                        .then(data => {
                            layero.find('#addPassword').val(data.password);
                        })
                        .catch(err => {
                            layer.msg(err.message || '生成失败');
                        });
                });
                
            }
        });
    }

    // 编辑用户
    function editUser(data) {
        const editIndex = layer.open({
            type: 1,
            title: '编辑用户 - ' + data.username,
            area: ['500px', 'auto'],
            btn: ['提交', '重置'],
            btnAlign: 'c',
            shadeClose: true,  // 点击遮罩层关闭
            content: `
                <form class="layui-form" style="padding: 20px;" lay-filter="editForm" id="editUserForm">
                    <input type="hidden" name="user_id" value="${data.id}">
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label">用户名</label>
                        <div class="layui-input-block">
                            <input type="text" name="username" value="${data.username || ''}" 
                                   placeholder="3-50字符" class="layui-input" required lay-verify="required">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label">姓名</label>
                        <div class="layui-input-block">
                            <input type="text" name="full_name" value="${data.full_name || ''}" 
                                   placeholder="选填" class="layui-input">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label">邮箱</label>
                        <div class="layui-input-block">
                            <input type="email" name="email" value="${data.email || ''}" 
                                   placeholder="邮箱地址" class="layui-input" required lay-verify="required|email">
                        </div>
                    </div>
                    
                    <div class="layui-form-item">
                        <label class="layui-form-label">密码</label>
                        <div class="layui-input-block">
                            <div style="display: flex; align-items: center;">
                                <input type="text" name="password" id="editPassword" 
                                       placeholder="不改请留空" class="layui-input" 
                                       style="flex: 1; margin-right: 8px;">
                                <button type="button" class="layui-btn layui-btn-primary" id="generateBtn" 
                                        title="随机生成" style="padding: 0 15px;">
                                    <i class="layui-icon layui-icon-refresh"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            `,
            yes: function(index, layero) {
                // 直接提交表单
                const formData = form.val('editForm');
                const userId = data.id;
                const submitData = {
                    username: formData.username?.trim() || '',
                    full_name: formData.full_name?.trim() || '',
                    email: formData.email?.trim() || ''
                };
                
                // 验证必填字段
                if (!submitData.username) {
                    layer.msg('请输入用户名', { icon: 2 });
                    return false;
                }
                if (!submitData.email) {
                    layer.msg('请输入邮箱', { icon: 2 });
                    return false;
                }
                
                // 只在有值时才添加密码字段
                const password = formData.password?.trim();
                if (password) {
                    submitData.password = password;
                }
                
                Api.apiRequest('/users/admin/' + userId, {
                    method: 'PUT',
                    body: JSON.stringify(submitData)
                })
                .then(res => {
                    layer.msg('更新成功', { icon: 1 });
                    layer.close(editIndex);
                    tableIns.reload();
                })
                .catch(error => {
                    layer.msg(error.message || '更新失败', { icon: 2 });
                });
                
                return false;
            },
            btn2: function(index, layero) {
                // 重置按钮
                form.val('editForm', {
                    username: data.username || '',
                    full_name: data.full_name || '',
                    email: data.email || '',
                    password: ''
                });
                return false;
            },
            success: function(layero, index) {
                form.render();
                
                // 随机密码按钮
                layero.find('#generateBtn').on('click', function() {
                    Api.apiRequest('/users/admin/generate-password')
                        .then(data => {
                            layero.find('#editPassword').val(data.password);
                        })
                        .catch(err => {
                            layer.msg(err.message || '生成失败');
                        });
                });
                
            }
        });
    }

    // 取消MFA
    function cancelMFA(data) {
        layer.confirm('确定要取消该用户的MFA吗？', {
            icon: 3,
            title: '提示'
        }, function(index) {
            Api.apiRequest('/users/admin/' + data.id + '/cancel-mfa', {
                method: 'POST'
            })
            .then(res => {
                layer.msg('MFA已取消');
                tableIns.reload();
            })
            .catch(error => {
                layer.msg(error.message || '操作失败');
                console.error(error);
            });
            layer.close(index);
        });
    }

    // 切换用户状态（启用/禁用）
    function toggleUserStatus(data, enable) {
        const action = enable ? '启用' : '禁用';
        
        Api.apiRequest('/users/admin/' + data.id + '/toggle-status', {
            method: 'POST'
        })
        .then(res => {
            layer.msg('账号已' + action);
            tableIns.reload();
        })
        .catch(error => {
            layer.msg(error.message || '操作失败');
            console.error(error);
        });
    }

    // 删除用户
    function deleteUser(data) {
        layer.confirm('确定要删除该用户吗？删除后无法恢复！', {
            icon: 3,
            title: '警告'
        }, function(index) {
            Api.apiRequest('/users/admin/' + data.id, {
                method: 'DELETE'
            })
            .then(res => {
                layer.msg('用户已删除');
                tableIns.reload();
            })
            .catch(error => {
                layer.msg(error.message || '删除失败');
                console.error(error);
            });
            layer.close(index);
        });
    }
});
