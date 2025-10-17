// 主应用文件
const App = {
    // 应用配置
    config: {
        token: localStorage.getItem('token'),
        currentUser: null,
        unreadCounts: {}, // 用于存储每个账户的未读邮件数
        lastClickedFolderId: null,
        lastClickTime: 0
    },

    // 初始化应用
    init: function() {
        this.bindEvents();
        this.checkAuthStatus();
        this.setupWebSocket();
        EmailModule.init();
    },

    // 绑定事件
    bindEvents: function() {
        $('#logout-btn').on('click', () => Api.handleLogout());
        $('#add-account-btn').on('click', () => AccountModule.loadAddAccount());
        $('#profile-btn').on('click', () => AccountModule.loadProfile());
        $('#mfa-settings-btn').on('click', () => {
            if (this.config.currentUser.is_mfa_enabled) {
                AccountModule.showDisableMfaModal();
            } else {
                AccountModule.showSetupMfaModal();
            }
        });
        
        // 账号管理按钮点击事件
        $('#admin-users-btn').on('click', () => {
            layui.layer.open({
                type: 2,
                title: '账号管理',
                area: ['100%', '100%'],
                content: 'admin-users.html',
                maxmin: true
            });
        });

        // 折叠所有文件夹功能（使用事件委托）
        $(document).on('click', '#toggle-folders-btn', () => {
            const accountItems = $('.account-list-item');
            
            // 先折叠所有展开的自定义文件夹（通过模拟点击折叠按钮）
            accountItems.find('.folder-toggle-icon.layui-icon-down').each(function() {
                $(this).trigger('click');
            });
            
            // 再折叠所有账户
            accountItems.removeClass('expanded');
            accountItems.find('.account-folder-dl').slideUp(200);
            accountItems.find('.toggle-icon-wrapper .layui-icon')
                .removeClass('layui-icon-down')
                .addClass('layui-icon-right');
        });

        const list = $('#account-folder-list');
        // 处理主条目区域的点击，用于折叠/展开
        list.on('click', '.account-item-main', function(e) {
            // 如果点击的是设置图标或其内部元素，则不执行折叠操作
            if ($(e.target).closest('.settings-icon-wrapper').length) {
                return;
            }
            e.stopPropagation();

            const listItem = $(this).closest('.account-list-item');
            
            // 切换折叠状态
            listItem.find('.toggle-icon-wrapper .layui-icon').toggleClass('layui-icon-right layui-icon-down');
            listItem.find('.account-folder-dl').slideToggle(200);

            // 点击账户名称不选中账户，只折叠/展开
        });

        // 单独处理刷新图标的点击
        list.on('click', '.refresh-icon-wrapper', function(e) {
            e.stopPropagation(); // 阻止事件冒泡到 .account-item-main
            const accountId = $(this).data('account-id');
            App.refreshAccountFolders(accountId, this);
        });

        // 单独处理设置图标的点击
        list.on('click', '.settings-icon-wrapper', function(e) {
            e.stopPropagation(); // 阻止事件冒泡到 .account-item-main
            const accountId = $(this).data('account-id');
            AccountModule.showAccountSettings(accountId, this);
        });

        // 右键菜单事件
        list.on('contextmenu', '.account-info-wrapper', function(e) {
            e.preventDefault();
            // 触发设置图标的点击事件，以显示菜单
            $(this).closest('.account-list-item').find('.settings-icon-wrapper').trigger('click');
        });
    },

    // 检查认证状态
    checkAuthStatus: function() {
        const token = this.config.token;
        if (!token) {
            if (!window.location.pathname.endsWith('login.html')) {
                window.location.href = 'login.html';
            }
            return;
        }

        this.getCurrentUser().then(async user => {
            if (user) {
                this.config.currentUser = user;
                $('#username-display').text(user.username);
                $('.layui-nav-img').attr('src', user.avatar || 'images/user-avatar.png');
                
                // 更新MFA按钮文本
                const mfaBtn = $('#mfa-settings-btn');
                if (mfaBtn.length) {
                    mfaBtn.text(user.is_mfa_enabled ? '取消MFA' : '绑定MFA');
                }
                
                // 显示/隐藏管理员菜单
                if (user.is_admin) {
                    $('#admin-menu-item').show();
                } else {
                    $('#admin-menu-item').hide();
                }

                await this.loadAccountFolders(); // 等待账户文件夹加载完成
            } else {
                Api.handleLogout();
            }
        }).catch(() => Api.handleLogout());
    },

    // 获取当前用户信息（使用Api的缓存方法）
    getCurrentUser: async function() {
        try {
            return await Api.getCurrentUser();
        } catch (error) {
            return null;
        }
    },

    // 递归渲染文件夹
    renderFolders: function(folders, accountId, level = 0) {
        let html = '';
        if (!folders || folders.length === 0) {
            return html;
        }
    
        const folderIconMap = {
            'INBOX': 'layui-icon-email',
            'UNREAD': 'layui-icon-dialogue',
            'Drafts': 'layui-icon-edit',  // 系统草稿箱
            'Sent': 'layui-icon-release',
            'Junk': 'layui-icon-fonts-clear',
            'Trash': 'layui-icon-delete',
            // 添加更多自定义文件夹图标
        };
    
        folders.forEach(folder => {
            const hasChildren = folder.children && folder.children.length > 0;
            const displayName = folder.display_name;
            const folderName = folder.name;
            const paddingLeft = 20 * level;
            
            const iconClass = folderIconMap[folderName] || 'layui-icon-folder';
            
            // 自定义文件夹判断（不包括固定文件夹，包含系统草稿箱Drafts）
            const isCustomFolder = !['INBOX', 'UNREAD', 'Drafts', 'Sent', 'Junk', 'Trash'].includes(folderName);
    
            html += `
                <dd style="padding-left: ${paddingLeft}px;" class="folder-item">
                    <div class="folder-item-container">
                        <div class="folder-column folder-toggle">
                            ${hasChildren ? '<i class="layui-icon layui-icon-right folder-toggle-icon"></i>' : ''}
                        </div>
                        <div class="folder-column folder-icon">
                            <i class="layui-icon ${iconClass}"></i>
                        </div>
                        <a href="javascript:void(0);"
                           class="folder-column folder-link"
                           data-account-id="${accountId}"
                           data-folder-name="${folderName}">
                           ${displayName}
                        </a>
                        <div class="folder-column folder-actions">
                            ${isCustomFolder ? '<i class="layui-icon layui-icon-add-1 add-subfolder-icon" title="添加子文件夹"></i><i class="layui-icon layui-icon-delete delete-folder-icon" title="删除文件夹"></i>' : ''}
                        </div>
                    </div>
                    ${hasChildren ? `<dl class="sub-folder-dl" style="display: none;">${this.renderFolders(folder.children, accountId, level + 1)}</dl>` : ''}
                </dd>
            `;
        });
        return html;
    },

    // 加载账户和文件夹列表
    loadAccountFolders: async function() {
        try {
            const accounts = await Api.apiRequest('/email-accounts');
            // 更新 EmailModule 的缓存
            EmailModule.cache.accounts = accounts;
            const container = $('#account-folder-list');
            container.html('');
            const lastOpened = JSON.parse(localStorage.getItem('lastOpenedFolder'));

            for (let i = 0; i < accounts.length; i++) {
                const account = accounts[i];
                const folders = await Api.apiRequest(`/email-accounts/${account.id}/folders`);
                let isExpanded = false;
                let isSelected = false;

                if (lastOpened) {
                    if (account.id === lastOpened.accountId) {
                        isExpanded = true;
                        isSelected = true;
                    }
                } else if (i === 0) {
                    isExpanded = true;
                    isSelected = true;
                }

                const unreadCount = await EmailModule.getUnreadCount(account.id);
                const foldersHtml = this.renderFolders(folders, account.id);

                const listItem = $(`
                    <li class="account-list-item ${isExpanded ? 'expanded' : ''} ${isSelected ? 'selected' : ''}" data-account-id="${account.id}">
                        <div class="account-item-main">
                            <div class="toggle-icon-wrapper">
                                <i class="layui-icon ${isExpanded ? 'layui-icon-down' : 'layui-icon-right'}"></i>
                            </div>
                            <a href="javascript:;" class="account-info-wrapper">
                                <span class="account-display">
                                    <span class="account-name">
                                        ${account.name || account.email}
                                        <span class="layui-badge layui-bg-gray" id="unread-badge-${account.id}" style="${unreadCount > 0 ? '' : 'display: none;'}">${unreadCount}</span>
                                    </span>
                                    ${account.name ? `<small class="account-email">${account.email}</small>` : ''}
                                </span>
                            </a>
                            <div class="refresh-icon-wrapper" data-account-id="${account.id}" title="刷新文件夹">
                                <i class="layui-icon layui-icon-refresh"></i>
                            </div>
                            <div class="settings-icon-wrapper" data-account-id="${account.id}">
                                <i class="layui-icon layui-icon-set"></i>
                            </div>
                        </div>
                        <dl class="account-folder-dl" style="${isExpanded ? 'display: block;' : 'display: none;'}">
                            ${foldersHtml}
                        </dl>
                    </li>
                `);
                container.append(listItem);
            }

            this.initSortable();
            
            const listContainer = $('#account-folder-list');
            // 统一处理文件夹点击事件
            listContainer.off('click', '.folder-link').on('click', '.folder-link', function(e) {
                e.stopPropagation(); // 阻止事件冒泡

                const accountId = $(this).data('account-id');
                const folderName = $(this).data('folder-name');
                const folderId = `${accountId}-${folderName}`;
                
                // 判断是否为标准文件夹（包括系统草稿箱Drafts）
                const isStandardFolder = ['INBOX', 'UNREAD', 'Drafts', 'Sent', 'Junk', 'Trash'].includes(folderName);
                const isCustomFolder = !isStandardFolder;

                const currentTime = new Date().getTime();
                if (folderId === App.config.lastClickedFolderId && (currentTime - App.config.lastClickTime < 3000)) {
                    if (!isCustomFolder) {
                        layui.layer.msg('请勿频繁点击', {icon: 7, time: 1000});
                    }
                    return;
                }
                App.config.lastClickedFolderId = folderId;
                App.config.lastClickTime = currentTime;
                
                // 移除所有账户和文件夹的选中状态
                $('#account-folder-list .selected').removeClass('selected');
                
                // 为当前点击的文件夹的父级 <dd> 添加 'selected' 类
                $(this).closest('dd.folder-item').addClass('selected');
                
                // 同时选中对应的账户项
                $(this).closest('.account-list-item').addClass('selected');

                EmailModule.loadEmailList(folderName, accountId, false, this);
            });

            // 为新的层级文件夹绑定折叠/展开事件
            listContainer.off('click', '.folder-toggle-icon').on('click', '.folder-toggle-icon', function(e) {
                e.stopPropagation();
                $(this).toggleClass('layui-icon-right layui-icon-down');
                $(this).closest('dd').find('.sub-folder-dl').first().slideToggle(200);

                // 切换文件夹打开/关闭图标
                const folderIcon = $(this).closest('.folder-item-container').find('.folder-icon .layui-icon');
                if (folderIcon.hasClass('layui-icon-folder') || folderIcon.hasClass('layui-icon-folder-open')) {
                    folderIcon.toggleClass('layui-icon-folder layui-icon-folder-open');
                }
            });

            // 点击文件夹图标也能选中
            listContainer.off('click', '.folder-icon').on('click', '.folder-icon', function(e) {
                e.stopPropagation();
                // 模拟点击文字链接
                $(this).siblings('.folder-link').trigger('click');
            });

            // 为添加子文件夹图标绑定事件
            listContainer.off('click', '.add-subfolder-icon').on('click', '.add-subfolder-icon', function(e) {
                e.stopPropagation();
                const folderItem = $(this).closest('.folder-item-container');
                const folderLink = folderItem.find('.folder-link');
                const accountId = folderLink.data('account-id');
                const parentFolder = folderLink.data('folder-name');
                AccountModule.createFolder(accountId, parentFolder);
            });

            // 为删除文件夹图标绑定事件
            listContainer.off('click', '.delete-folder-icon').on('click', '.delete-folder-icon', function(e) {
                e.stopPropagation();
                const folderItem = $(this).closest('.folder-item-container');
                const folderLink = folderItem.find('.folder-link');
                const accountId = folderLink.data('account-id');
                const folderName = folderLink.data('folder-name');
                App.deleteFolder(accountId, folderName);
            });

            // 右键菜单事件 - 直接重命名
            listContainer.off('contextmenu', '.folder-link').on('contextmenu', '.folder-link', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const accountId = $(this).data('account-id');
                const folderName = $(this).data('folder-name');
                
                // 判断是否为标准文件夹（包括系统草稿箱Drafts）
                const isStandardFolder = ['INBOX', 'UNREAD', 'Drafts', 'Sent', 'Junk', 'Trash'].includes(folderName);
                const isCustomFolder = !isStandardFolder;

                if (isCustomFolder) {
                    AccountModule.renameFolder(accountId, folderName);
                }
            });

            // 双击展开/折叠文件夹
            listContainer.off('dblclick', '.folder-item-container').on('dblclick', '.folder-item-container', function(e) {
                e.preventDefault();
                e.stopPropagation();
                $(this).find('.folder-toggle-icon').trigger('click');
            });

            if (lastOpened) {
                // 查找对应的文件夹链接
                const targetFolderLink = $(`a.folder-link[data-account-id='${lastOpened.accountId}'][data-folder-name='${lastOpened.folder}']`);
                if (targetFolderLink.length > 0) {
                    // 展开所有父级文件夹
                    targetFolderLink.parents('.sub-folder-dl').show().each(function() {
                        $(this).prev('.folder-item-container').find('.folder-toggle-icon')
                            .removeClass('layui-icon-right').addClass('layui-icon-down');
                    });
                    
                    // 触发点击事件来加载邮件列表并设置选中状态
                    targetFolderLink.trigger('click');
                } else {
                    // 如果找不到特定文件夹，就加载账户的默认文件夹
                    EmailModule.loadEmailList('INBOX', lastOpened.accountId, false);
                }
            } else {
                // 如果没有 lastOpened，默认加载第一个账户的INBOX
                const firstAccount = accounts[0];
                if(firstAccount) {
                    EmailModule.loadEmailList('INBOX', firstAccount.id, false);
                }
            }

        } catch (error) {
            console.error('加载邮箱账户或文件夹失败:', error);
        }
    },

    // 初始化拖拽排序
    initSortable: function() {
        const el = $('#account-folder-list');
        if (el.data('sortable')) {
            el.data('sortable').destroy();
        }
        const sortable = new Sortable(el[0], {
            animation: 150,
            onEnd: (evt) => {
                const accountIds = el.find('.account-list-item').map(function() {
                    return $(this).data('account-id');
                }).get();
                this.updateAccountOrder(accountIds);
            }
        });
        el.data('sortable', sortable);
    },

    // 更新未读邮件徽章
    updateUnreadCountBadge: function(accountId, count) {
        const badge = $(`#unread-badge-${accountId}`);
        if (badge.length) {
            if (count > 0) {
                badge.text(count).show();
            } else {
                badge.hide();
            }
        }
    },

    // 更新账户排序
    updateAccountOrder: async function(accountIds) {
        try {
            await Api.apiRequest('/email-accounts/order', {
                method: 'PUT',
                body: JSON.stringify({ account_ids: accountIds })
            });
            layui.layer.msg('排序已更新', { icon: 1 });
        } catch (error) {
            layui.layer.msg('排序更新失败', { icon: 2 });
            console.error('更新账户排序失败:', error);
        } finally {
            // 无论成功与否，都重新加载以确保UI同步
            this.loadAccountFolders();
        }
    },

    // 加- 邮件列表
    loadEmailList: async function(folder, accountId) {
        EmailModule.loadEmailList(folder, accountId);
    },

    deleteFolder: async function(accountId, folderName) {
        layer.confirm('确定要删除该文件夹吗？此操作不可恢复。', {
            title: '确认删除',
            icon: 3
        }, async (index) => {
            try {
                await Api.apiRequest(`/email-accounts/${accountId}/folders`, {
                    method: 'DELETE',
                    body: JSON.stringify({ folder_name: folderName })
                });
                layer.close(index);
                layer.msg('文件夹删除成功', { icon: 1 });
                this.loadAccountFolders(); // 刷新文件夹列表
            } catch (error) {
                console.error('删除文件夹失败:', error);
                layer.msg(error.message || '删除文件夹失败', { icon: 2 });
            }
        });
    },

    // 辅助函数：格式化发件人信息
    formatSender: function(sender) {
        if (!sender) return { name: '未知发件人', address: '' };
        const match = sender.match(/(.*)<(.*)>/);
        if (match) {
            return { name: match[1].trim(), address: match[2].trim() };
        }
        // 如果没有匹配到 <...> 格式，尝试用正则表达式查找邮箱
        const emailMatch = sender.match(/([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)/);
        if (emailMatch) {
            const address = emailMatch[0];
            const name = sender.replace(address, '').trim();
            return { name: name || address, address: address };
        }
        return { name: sender, address: '' };
    },

    // 渲染邮件列表
    renderEmailList: function(emails, folder) {
        const container = $('#email-list-container');
        const detailContainer = $('#email-detail-container');
        const iframe = detailContainer.find('#email-content-iframe');
        const placeholder = detailContainer.find('.placeholder');
        
        iframe.hide();
        placeholder.show();

        if (!emails || emails.length === 0) {
            container.html(`<div class="placeholder">没有邮件</div>`);
            return;
        }
        
        const emailList = $('<div class="email-list"></div>');
        emails.forEach(email => {
            const senderInfo = this.formatSender(email.sender);
            const displaySender = senderInfo.name || senderInfo.address;
            
            const item = $(`
                <div class="email-item ${!email.is_read ? 'unread' : ''}" onclick="App.viewEmail(${email.email_account_id}, ${email.id}, this)">
                    <div class="email-item-header">
                        <div class="email-sender" title="${escapeHtml(email.sender)}">${escapeHtml(displaySender)}</div>
                        <div class="email-time">${new Date(email.received_date).toLocaleString()}</div>
                    </div>
                    <div class="email-subject">${escapeHtml(email.subject)}</div>
                    <div class="email-preview">${escapeHtml(email.body_text?.substring(0, 100)) || '无内容预览'}</div>
                </div>
            `);
            emailList.append(item);
        });
        container.html(emailList);
    },

    // 查看邮件详情
    viewEmail: async function(accountId, emailId, element) {
        $('.email-item.selected').removeClass('selected');
        $(element).addClass('selected');
        try {
            const email = await Api.apiRequest(`/email-accounts/${accountId}/emails/${emailId}`);
            this.renderEmailDetail(email);
        } catch (error) {
            $('#email-detail-container').html('<div class="placeholder">加载邮件失败</div>');
        }
    },

    // 渲染邮件详情
    renderEmailDetail: function(email) {
        const detailContainer = $('#email-detail-container');
        const iframe = detailContainer.find('#email-content-iframe');
        const placeholder = detailContainer.find('.placeholder');
        
        const senderInfo = this.formatSender(email.sender);
        const displaySender = senderInfo.address 
            ? `${escapeHtml(senderInfo.name)} <${escapeHtml(senderInfo.address)}>`
            : escapeHtml(senderInfo.name);

        const emailContentHtml = `
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }
                    .email-detail-header { border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px; }
                    .email-detail-subject { font-size: 22px; margin: 0 0 10px; }
                    .email-detail-meta p { margin: 2px 0; color: #666; }
                    .email-detail-content { margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="email-detail-header">
                    <h2 class="email-detail-subject">${escapeHtml(email.subject)}</h2>
                    <div class="email-detail-meta">
                        <p><strong>发件人:</strong> ${displaySender}</p>
                        <p><strong>收件人:</strong> ${escapeHtml(email.to) || '未知'}</p>
                        <p><strong>时间:</strong> ${new Date(email.received_date).toLocaleString()}</p>
                    </div>
                </div>
                <div class="email-detail-content">${email.body_html || (escapeHtml(email.body_text) || '').replace(/\n/g, '<br>') || '无邮件内容'}</div>
            </body>
            </html>
        `;

        iframe.prop('srcdoc', emailContentHtml);
        placeholder.hide();
        iframe.show();
    },

    // 设置WebSocket连接
    setupWebSocket: function() {
        const token = localStorage.getItem('token'); // 始终从localStorage获取最新token
        if (!token) return;

        // 如果已有连接，先关闭
        if (this.ws && this.ws.readyState !== WebSocket.CLOSED) {
            console.log('关闭旧的WebSocket连接');
            this.ws.close();
        }

        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const wsUrl = `${protocol}://${location.host}/ws/sync?token=${token}`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket连接已建立');
            this.ws.send(JSON.stringify({ action: 'get_drafts' }));
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                switch (data.status) {
                    case 'new_mail':
                        console.log('收到新邮件通知:', data);
                        // 刷新左侧列表以更新未读计数
                        App.loadAccountFolders();
                        // 检查当前选中的账户是否是收到新邮件的账户，并且选中的文件夹是收件箱
                        if (EmailModule.cache.currentAccount == data.accountId && EmailModule.cache.currentFolder === 'INBOX') {
                            EmailModule.loadEmailList(EmailModule.cache.currentFolder, EmailModule.cache.currentAccount);
                            layui.layer.msg('您有新邮件，已自动刷新');
                        }
                        break;
                    case 'unread_count_update':
                        for (const accountId in data.counts) {
                            const newCount = data.counts[accountId];
                            const oldCount = App.config.unreadCounts[accountId] || 0;
                            if (newCount !== oldCount) {
                                console.log(`账户 ${accountId} 的未读邮件数从 ${oldCount} 更新为 ${newCount}`);
                                App.updateUnreadCountBadge(accountId, newCount);
                                App.config.unreadCounts[accountId] = newCount;
                            }
                        }
                        break;
                    case 'sync_failed':
                        console.error('邮件同步失败通知:', data);
                        // 尝试从页面元素获取账户名称
                        const accountItem = $(`.account-list-item[data-account-id='${data.accountId}']`);
                        const accountName = accountItem.length ? accountItem.find('.account-name').text() : `账户ID ${data.accountId}`;
                        layui.layer.msg(`邮箱 ${accountName} 同步失败，请检查配置或稍后重试`, { icon: 2, time: 5000 });
                        break;
                    case 'heartbeat':
                        // console.log('收到心跳消息');
                        break;
                    case 'no_update':
                        // console.log('邮件检查完成，无更新');
                        break;
                    case 'drafts_update':
                        console.log('收到草稿更新:', data);
                        if (EmailModule.currentFolder === 'Drafts') {
                            EmailModule.renderEmailList(data.drafts, false);
                        }
                        break;
                    default:
                        console.log('收到未知WebSocket消息:', data);
                }
            } catch (error) {
                console.error('处理WebSocket消息失败:', error);
            }
        };

        this.ws.onclose = () => {
            console.log('WebSocket连接已断开');
            // 只在非主动断开时才自动重连
            if (!this.wsManualClose) {
                console.log('5秒后尝试重连WebSocket');
                setTimeout(() => {
                    this.setupWebSocket();
                }, 5000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
        };
    },

    // Token续期后重连WebSocket
    reconnectWebSocket: function() {
        console.log('%c↻ Token已更新，重连WebSocket使用新token', 'color: blue; font-weight: bold;');
        this.wsManualClose = true; // 标记为主动断开
        
        // 关闭旧连接
        if (this.ws && this.ws.readyState !== WebSocket.CLOSED) {
            this.ws.close();
        }
        
        // 等待旧连接完全关闭后重连
        setTimeout(() => {
            this.wsManualClose = false;
            this.setupWebSocket();
        }, 500);
    },

    // 刷新指定账户的文件夹列表
    refreshAccountFolders: async function(accountId, triggerElement) {
        const $trigger = $(triggerElement);
        const $icon = $trigger.find('.layui-icon');
        
        // 防止重复点击
        if ($trigger.hasClass('refreshing')) {
            return;
        }
        
        $trigger.addClass('refreshing');
        $icon.addClass('layui-icon-loading layui-anim layui-anim-rotate layui-anim-loop');
        
        try {
            console.log(`开始刷新账户 ${accountId} 的文件夹列表`);
            
            // 获取最新的文件夹列表
            const folders = await Api.apiRequest(`/email-accounts/${accountId}/folders`);
            
            // 找到对应的账户项
            const $accountItem = $(`.account-list-item[data-account-id="${accountId}"]`);
            const $folderContainer = $accountItem.find('.account-folder-dl');
            
            // 记录当前展开的文件夹
            const expandedFolders = [];
            $folderContainer.find('.folder-toggle-icon.layui-icon-down').each(function() {
                const folderName = $(this).closest('.folder-item-container').find('.folder-link').data('folder-name');
                expandedFolders.push(folderName);
            });
            
            // 重新渲染文件夹
            const foldersHtml = this.renderFolders(folders, accountId);
            $folderContainer.html(foldersHtml);
            
            // 恢复之前展开的文件夹状态
            expandedFolders.forEach(folderName => {
                const $folderLink = $folderContainer.find(`.folder-link[data-folder-name="${folderName}"]`);
                if ($folderLink.length) {
                    const $container = $folderLink.closest('.folder-item-container');
                    $container.find('.folder-toggle-icon')
                        .removeClass('layui-icon-right')
                        .addClass('layui-icon-down');
                    $folderLink.closest('dd').find('.sub-folder-dl').first().show();
                }
            });
            
            layui.layer.msg('文件夹列表已刷新', { icon: 1, time: 1000 });
            console.log(`账户 ${accountId} 的文件夹列表刷新完成`);
            
        } catch (error) {
            console.error('刷新文件夹列表失败:', error);
            layui.layer.msg('刷新失败: ' + (error.detail || error.message), { icon: 2 });
        } finally {
            // 移除加载状态
            setTimeout(() => {
                $trigger.removeClass('refreshing');
                $icon.removeClass('layui-icon-loading layui-anim layui-anim-rotate layui-anim-loop');
            }, 500);
        }
    }
};
