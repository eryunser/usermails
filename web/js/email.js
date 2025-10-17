// 邮件相关功能模块
const EmailModule = {
    // 缓存数据
    cache: {
        accounts: [], // 邮箱账号列表（包括账号的Folder）
        currentAccount: null, // 当前选择的邮箱账号
        currentFolder: null, // 当前选择的文件夹
        currentEmail: null, // 当前查看的邮件
        currentPage: 1, // 分页页码
    },
    
    // 草稿相关
    draft: {
        current: null, // 当前编辑的草稿对象
        saveInterval: null, // 自动保存定时器
        statusUpdateInterval: null, // 状态更新定时器
        lastSaveTime: null, // 最后保存时间
        attachments: [], // 待发送的附件列表
    },
    
    isLoading: false,

    // 格式化时间为“xx秒前”
    formatTimeAgo: function(date) {
        if (!date) return '';
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 1) {
            return "刚刚";
        }
        if (seconds < 60) {
            return `${seconds} 秒前`;
        }
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) {
            return `${minutes} 分钟前`;
        }
        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
            return `${hours} 小时前`;
        }
        const days = Math.floor(hours / 24);
        return `${days} 天前`;
    },

    // Correctly escape HTML to prevent rendering issues
    escapeHTML: function(str) {
        if (!str) return '';
        return str.replace(/&/g, '&')
            .replace(/</g, '<')
            .replace(/>/g, '>')
            .replace(/"/g, '"')
            .replace(/'/g, '&#039;');
    },

    formatSender: function(sender) {
        if (typeof sender !== 'string') {
            return '未知发件人'; // 或者返回一个空字符串 ''
        }
        sender = sender.trim();
    
        // 情况1: 包含 <...>，用你的正则分割
        const angleBracketMatch = sender.match(/^(.*)\s*<([^>]+)>$/);
        if (angleBracketMatch) {
            let name = angleBracketMatch[1].trim();
            const email = angleBracketMatch[2].trim();
    
            // 清理名称中的引号（如 "John Doe"）
            name = name.replace(/^"(.*)"$/, '$1').trim();
    
            // 如果名称为空，用邮箱作为显示名
            if (!name) name = email;
    
            return `${name} <span class="email-sender-email">${email}</span>`;
        }
    
        // 情况2: 不包含 <...>，整个字符串视为邮箱
        // 可选：简单验证是否像邮箱
        if (/@/.test(sender)) {
            return `${sender} <span class="email-sender-email">${sender}</span>`;
        }
    
        // 情况3: 无法识别，返回原样
        return sender;
    },

    init: function() {
        const container = $('#email-list-wrapper');
        if (container.length) {
            container.on('scroll', () => {
                if (container.scrollTop() + container.innerHeight() >= container[0].scrollHeight - 5) {
                    this.loadEmailList(this.cache.currentFolder, this.cache.currentAccount, true);
                }
            });
        }

        $('#select-all-emails').on('change', (event) => {
            const container = $('#email-list-container');
            // When checking the "select all" box, ensure multi-select mode is enabled.
            if ($(event.target).is(':checked')) {
                container.addClass('multi-select-mode');
            }

            $('.email-item .email-checkbox').prop('checked', $(event.target).is(':checked'));
        });

        $('#delete-selected-emails').on('click', () => this.deleteSelectedEmails());
        $('#permanent-delete-selected-emails').on('click', () => this.permanentDeleteSelectedEmails());
        $('#mark-read-btn').on('click', () => this.markAsRead());
        $('#refresh-email-list').on('click', () => this.loadEmailList(this.cache.currentFolder, this.cache.currentAccount));
        
        // 添加搜索按钮事件
        const searchBtn = $('#search-btn');
        if (searchBtn.length) {
            searchBtn.on('click', () => {
                const keyword = $('#keyword-search-input').val();
                const sender = $('#sender-search-input').val();
                this.loadEmailList(this.cache.currentFolder, this.cache.currentAccount, false, null, keyword, sender);
            });
        }

        $('#multi-select-btn').on('click', () => {
            const container = $('#email-list-container');
            const isExiting = container.hasClass('multi-select-mode');
            
            container.toggleClass('multi-select-mode');

            // If we were in multi-select mode and are now exiting, uncheck all boxes
            if (isExiting) {
                $('#select-all-emails').prop('checked', false);
                $('.email-item .email-checkbox').prop('checked', false);
            }
        });
    },

    getUnreadCount: async function(accountId) {
        try {
            const response = await Api.apiRequest(`/email-accounts/${accountId}/unread-count`);
            return response.unread_count || 0;
        } catch (error) {
            console.error('获取未读邮件数失败:', error);
            return 0;
        }
    },

    // 加载邮件列表
    loadEmailList: async function(folder, accountId, append = false, targetElement, keyword, sender) {
        if (this.isLoading) return;

        if (!append) {
            this.cache.currentPage = 1;
            this.cache.currentFolder = folder;
            this.cache.currentAccount = accountId;
            $('#email-list-wrapper').html('');

            // 如果不是搜索触发的加载，则清空搜索框
            if (keyword === undefined && sender === undefined) {
                const keywordInput = $('#keyword-search-input');
                const senderInput = $('#sender-search-input');
                if (keywordInput.length) keywordInput.val('');
                if (senderInput.length) senderInput.val('');
            }

            // 保存最后打开的文件夹
            localStorage.setItem('lastOpenedFolder', JSON.stringify({ accountId, folder }));

            // 移除所有文件夹的选中状态
            $('#account-folder-list .folder-item').removeClass('selected');
            
            // 为当前文件夹添加选中状态
            if (targetElement) {
                $(targetElement).closest('.folder-item').addClass('selected');
            } else {
                // 如果没有 targetElement（例如，在页面加载时），则通过 data 属性查找
                const folderLink = $(`a[data-account-id='${accountId}'][data-folder-name='${folder}']`);
                if (folderLink.length) {
                    folderLink.closest('.folder-item').addClass('selected');
                }
            }
        }

        // 根据文件夹调整按钮可见性
        const isSpecialFolder = ['Drafts', 'Sent'].includes(folder);
        $('#delete-selected-emails').toggle(!isSpecialFolder);
        $('#permanent-delete-selected-emails').show();

        this.isLoading = true;
        try {
            let apiUrl;
            let params = new URLSearchParams({
                skip: (this.cache.currentPage - 1) * 50,
                limit: 50
            });

            // 草稿箱使用专门的草稿接口
            if (folder === 'Drafts') {
                apiUrl = `/email-accounts/${accountId}/drafts?${params.toString()}`;
            } else {
                if (folder === 'UNREAD') {
                    params.set('folder', 'INBOX');
                    params.set('is_read', 'false');
                } else {
                    params.set('folder', folder);
                }

                if (keyword) {
                    params.append('keyword', keyword);
                }
                if (sender) {
                    params.append('sender', sender);
                }

                apiUrl = `/email-accounts/${accountId}/emails?${params.toString()}`;
            }

            const emails = await Api.apiRequest(apiUrl);
            if (emails.length > 0) {
                this.cache.currentPage++;
                this.renderEmailList(emails, append);
            }
        } catch (error) {
            console.error('加载邮件列表失败:', error);
        } finally {
            this.isLoading = false;
        }
    },

    // 渲染邮件列表
    renderEmailList: function(emails, append) {
        const container = $('#email-list-wrapper');
        if (!container.length) {
            console.error("错误: 未找到ID为 'email-list-wrapper' 的元素。");
            return;
        }

        if (!append) {
            // Clear the container only if it's a fresh load
            container.html(''); 
        }

        if (!emails || emails.length === 0) {
            if (!append) {
                container.html('<div>该文件夹下没有邮件</div>');
                container.addClass('is-empty');
            }
            return;
        }

        container.removeClass('is-empty');
        let emailList = container.find('.email-list');
        if (!emailList.length) {
            emailList = $('<div class="email-list"></div>');
            container.append(emailList);
        }

        emails.forEach(email => {
            const item = $('<div></div>')
                .addClass(`email-item ${!email.is_read ? 'unread' : ''}`)
                .attr('data-email-id', email.id);

            const escapedSender = this.formatSender(email.sender);
            const escapedSubject = this.escapeHTML(email.subject);
            const escapedPreview = this.escapeHTML(email.summary || '');

            const isSpecialFolder = ['Drafts', 'Sent'].includes(this.cache.currentFolder);
            let actionsHtml = '<div class="layui-btn-group">';
            if (!isSpecialFolder) {
                actionsHtml += `<button class="layui-btn layui-btn-primary layui-btn-xs" onclick="event.stopPropagation(); EmailModule.moveEmail(${email.email_account_id}, ${email.id}, '${this.cache.currentFolder}');" title="移动"><i class="layui-icon layui-icon-right"></i></button>`;
                actionsHtml += `<button class="layui-btn layui-btn-primary layui-btn-xs" onclick="event.stopPropagation(); EmailModule.deleteEmail(${email.email_account_id}, ${email.id});" title="删除"><i class="layui-icon layui-icon-delete"></i></button>`;
            }
            actionsHtml += `<button class="layui-btn layui-btn-primary layui-btn-xs" onclick="event.stopPropagation(); EmailModule.permanentDeleteEmail(${email.email_account_id}, ${email.id});" title="彻底删除"><i class="layui-icon layui-icon-close-fill"></i></button>`;
            actionsHtml += '</div>';

            item.html(`
                <div class="email-checkbox-wrapper">
                    <input type="checkbox" class="email-checkbox" data-email-id="${email.id}" lay-skin="primary">
                </div>
                <div class="email-content" onclick="EmailModule.viewEmail(${email.email_account_id}, ${email.id}, this)">
                    <div class="email-sender">${escapedSender}</div>
                    <div class="email-subject" title="${escapedSubject}">${escapedSubject}</div>
                    <div class="email-preview" title="${escapedPreview}">${escapedPreview}</div>
                </div>
                <div class="email-item-actions">
                    ${actionsHtml}
                </div>
            `);
            emailList.append(item);
        });

        // Re-render checkboxes for LayUI
        layui.form.render('checkbox');
    },

    // 查看邮件详情
    viewEmail: async function(accountId, emailId, element) {
        // 检查是否为草稿
        if (this.cache.currentFolder === 'Drafts') {
            try {
                // 草稿现在从专门的接口获取
                const draft = await Api.apiRequest(`/email-accounts/${accountId}/drafts/${emailId}`);
                this.openComposeModal({
                    title: '编辑草稿',
                    to: draft.recipients,
                    cc: draft.cc,
                    subject: draft.subject,
                    body: draft.body,
                    draftId: draft.id
                });
            } catch (error) {
                console.error('加载草稿失败:', error);
                layui.layer.msg('加载草稿失败');
            }
            return;
        }

        const detailContainer = $('#email-detail-container');
        const loadingIndex = layer.load(1, {
            shade: [0.8, '#fff'],
            target: detailContainer,
            time: 10000 // 最长等待时间10秒
        });

        try {
            // 移除之前选中的邮件的 'selected' 类
            $('.email-item.selected').removeClass('selected');

            // 并行获取邮件元数据和解析后的HTML内容
            const [email, emailContentResponse] = await Promise.all([
                Api.apiRequest(`/email-accounts/${accountId}/emails/${emailId}?folder=${this.cache.currentFolder}`),
                Api.apiRequest(`/email-accounts/${accountId}/emails/${emailId}/content?folder=${this.cache.currentFolder}`)
            ]);
            
            // 存储当前邮件
            this.cache.currentEmail = email;
            this.cache.currentEmail.html_content = emailContentResponse.content;
            this.cache.currentEmail.attachments = emailContentResponse.attachments || [];

            // 渲染邮件详情
            EmailModule.renderEmailDetail(email, emailContentResponse.content, emailContentResponse.attachments);

            // 更新邮件列表中的状态
            const emailItem = $(`.email-item[data-email-id='${emailId}']`);
            if (emailItem.length) {
                emailItem.removeClass('unread').addClass('selected'); // 添加 'selected' 类
            }

        } catch (error) {
            console.error('加载邮件详情失败:', error);
            layui.layer.msg('加载邮件详情失败');
        } finally {
            layer.close(loadingIndex);
        }
    },

    // 渲染邮件详情
    renderEmailDetail: function(email, htmlContent, attachments = []) {
        const container = $('#email-detail-container');
        if (!container.length) {
            console.error("错误: 未找到ID为 'email-detail-container' 的元素。");
            return;
        }

        const to = email.to ? this.formatSender(email.to) : '无';
        const cc = email.cc ? this.escapeHTML(email.cc) : '无';
        const sender = email.sender ? this.formatSender(email.sender) : '无';

        // 格式化附件大小
        const formatFileSize = (bytes) => {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        };

        // 获取文件类型和对应的图标
        const getFileTypeAndIcon = (filename) => {
            if (!filename) return { type: 'file-other', icon: 'layui-icon-file' };
            
            const ext = filename.split('.').pop().toLowerCase();
            
            // 图片文件
            const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'tif'];
            if (imageExts.includes(ext)) {
                return { type: 'file-image', icon: 'layui-icon-picture' };
            }
            
            // 文档文件
            const docExts = ['pdf', 'doc', 'docx', 'txt', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'rtf', 'csv'];
            if (docExts.includes(ext)) {
                return { type: 'file-document', icon: 'layui-icon-file' };
            }
            
            // 压缩文件
            const archiveExts = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'tgz'];
            if (archiveExts.includes(ext)) {
                return { type: 'file-archive', icon: 'layui-icon-layer' };
            }
            
            // 其他文件
            return { type: 'file-other', icon: 'layui-icon-file' };
        };

        // 生成附件HTML - 添加token到下载URL
        let attachmentsHtml = '';
        if (attachments && attachments.length > 0) {
            const token = localStorage.getItem('token');
            attachmentsHtml = `
                <div class="email-attachments">
                    <div class="attachments-title"><i class="layui-icon layui-icon-file"></i> 附件 (${attachments.length})</div>
                    <div class="attachments-list">
                        ${attachments.map(att => {
                            const { type, icon } = getFileTypeAndIcon(att.filename);
                            return `
                                <div class="attachment-item ${type}" 
                                     data-filename="${this.escapeHTML(att.filename)}"
                                     data-url="${Api.config.apiBaseUrl}/email-accounts/${email.email_account_id}/emails/${email.id}/attachments/${att.index}"
                                     onclick="EmailModule.downloadAttachment(this, '${this.escapeHTML(att.filename)}')">
                                    <i class="layui-icon ${icon}"></i>
                                    <div class="attachment-info">
                                        <div class="attachment-name">${this.escapeHTML(att.filename)}</div>
                                        <div class="attachment-size">${formatFileSize(att.size)}</div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
        }

        // 渲染邮件元信息
        const isSpecialFolder = ['Drafts', 'Sent'].includes(this.cache.currentFolder);
        container.html(`
            <div class="email-detail">
                <div class="email-info-panel expanded">
                    <div class="email-subject" onclick="this.parentElement.classList.toggle('expanded')">${this.escapeHTML(email.subject)}</div>
                    <div class="info-content">
                        <div class="info-grid">
                            <div class="info-label">发件人:</div><div class="info-value">${sender}</div>
                            <div class="info-label">收件人:</div><div class="info-value">${to}</div>
                            <div class="info-label">时间:</div><div class="info-value">${new Date(email.received_date).toLocaleString()}</div>
                            <div class="info-label">抄送:</div><div class="info-value">${cc}</div>
                        </div>
                        ${attachmentsHtml}
                        <div class="email-actions">
                            <div class="layui-btn-group">
                                <button class="layui-btn layui-btn-primary layui-btn-sm" onclick="EmailModule.replyEmail(${email.id})"><i class="layui-icon layui-icon-reply-fill"></i> 回复</button>
                                <button class="layui-btn layui-btn-primary layui-btn-sm" onclick="EmailModule.forwardEmail(${email.id})"><i class="layui-icon layui-icon-next"></i> 转发</button>
                                <button class="layui-btn layui-btn-primary layui-btn-sm" onclick="EmailModule.deleteEmail(${email.email_account_id}, ${email.id})" style="display: ${isSpecialFolder ? 'none' : 'inline-block'};"><i class="layui-icon layui-icon-delete"></i> 删除</button>
                                <button class="layui-btn layui-btn-primary layui-btn-sm" onclick="EmailModule.permanentDeleteEmail(${email.email_account_id}, ${email.id})"><i class="layui-icon layui-icon-close-fill"></i> 彻底删除</button>
                                <button class="layui-btn layui-btn-primary layui-btn-sm" onclick="EmailModule.markAsUnread(${email.email_account_id}, ${email.id})" style="display: ${isSpecialFolder ? 'none' : 'inline-block'};"><i class="layui-icon layui-icon-email"></i> 标记为未读</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="email-body-container">
                    <iframe id="email-content-iframe" frameborder="0" style="width: 100%; height: 100%;"></iframe>
                </div>
            </div>
        `);

        // 将邮件内容写入 iframe
        const iframe = $('#email-content-iframe');
        if (iframe.length) {
            iframe.prop('srcdoc', htmlContent);
        }
    },

    deleteSelectedEmails: async function() {
        const selectedIds = this.getSelectedEmailIds();
        if (selectedIds.length === 0) {
            layui.layer.msg('请先选择邮件');
            return;
        }

        // 如果是草稿箱，则调用彻底删除
        if (this.cache.currentFolder === 'Drafts') {
            this.permanentDeleteSelectedEmails();
            return;
        }

        try {
            await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}/emails`, {
                method: 'DELETE',
                body: JSON.stringify({ email_ids: selectedIds })
            });
            layui.layer.msg('删除成功');
            // Remove selected items from the DOM
            selectedIds.forEach(id => {
                $(`.email-item[data-email-id='${id}']`).remove();
            });
            // Clear detail view if the current email was deleted
            const detailContainer = $('#email-detail-container');
            if (detailContainer.html() !== '' && selectedIds.includes(this.cache.currentEmail?.id)) {
                detailContainer.html('<div class="placeholder">请选择邮件以查看详情</div>');
            }
        } catch (error) {
            console.error('删除邮件失败:', error);
            layui.layer.msg('删除失败');
        }
    },

    markAsRead: async function() {
        const selectedIds = this.getSelectedEmailIds();
        
        if (selectedIds.length > 0) {
            // Mark selected as read
            try {
                await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}/emails/mark-as-read`, {
                    method: 'POST',
                    body: JSON.stringify({ email_ids: selectedIds })
                });
                layui.layer.msg('标记成功');
                // Update UI directly
                selectedIds.forEach(id => {
                    $(`.email-item[data-email-id='${id}']`).removeClass('unread');
                });
            } catch (error) {
                console.error('标记已读失败:', error);
                layui.layer.msg('标记失败');
            }
        } else {
            // Mark all as read
            try {
                await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}/emails/mark-all-as-read`, {
                    method: 'POST',
                    body: JSON.stringify({ folder: this.cache.currentFolder })
                });
                layui.layer.msg('全部标记成功');
                // Update UI directly
                $('.email-item.unread').removeClass('unread');
            } catch (error) {
                console.error('全部标记已读失败:', error);
                layui.layer.msg('全部标记失败');
            }
        }
    },

    getSelectedEmailIds: function() {
        return $('.email-item .email-checkbox:checked').map(function() {
            return parseInt($(this).data('email-id'));
        }).get();
    },

    openComposeModal: async function(options = {}) {
        const { title = '写邮件', to = '', cc = '', subject = '', body = '', draftId = null } = options;
        
        // 检查系统中是否有邮箱账号（使用缓存）
        let accounts = this.cache.accounts;
        if (!accounts || accounts.length === 0) {
            layui.layer.msg('请先添加邮箱账号', { icon: 7 });
            return;
        }
        
        // 检查是否选中了邮箱账号
        if (!this.cache.currentAccount) {
            layui.layer.msg('请先选择一个邮箱账号', { icon: 7 });
            return;
        }
        
        // 获取当前账号信息以显示在标题中
        let accountName = '';
        try {
            const account = await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}`);
            accountName = account.name || account.email;
        } catch (error) {
            console.error('获取账号信息失败:', error);
            accountName = '未知账号';
        }
        
        this.draft.current = draftId;
        this.draft.lastSaveTime = null;
        this.draft.attachments = [];

        // 重置表单
        $('#compose-email-modal form')[0].reset();
        $('#compose-to').val(to);
        $('#compose-cc').val(cc);
        $('#compose-subject').val(subject);
        $('#draft-save-status').text(''); // 清空状态
        $('#attachment-list').empty(); // 清空附件列表

        layer.open({
            type: 1,
            title: `${title} - ${accountName}`,
            area: ['1000px', '600px'],
            content: $('#compose-email-modal'),
            maxmin: true, // 开启最大化按钮
            shadeClose: true,
            btn: ['立即发送', '重置'],
            btnAlign: 'c', // 按钮居中
            yes: function(index, layero) {
                const form = $('#compose-email-modal form');
                const to = form.find('#compose-to').val();
                const cc = form.find('#compose-cc').val();
                const subject = form.find('#compose-subject').val();
                const body = editor.txt.html();

                if (!to || !subject) {
                    layui.layer.msg('收件人和主题不能为空');
                    return;
                }

                EmailModule.sendEmail({ 
                    to, 
                    cc, 
                    subject, 
                    body, 
                    draft_id: EmailModule.draft.current 
                });
                layer.close(index);
            },
            btn2: function(index, layero) {
                // 重置按钮
                $('#compose-email-modal form')[0].reset();
                editor.txt.html('');
                return false; // 阻止弹层关闭
            },
            success: function(layero, index) {
                if (editor) {
                    editor.destroy();
                    editor = null;
                }
                const E = window.wangEditor;
                editor = new E('#compose-body-editor');

                // 配置图片上传
                editor.config.uploadImgServer = `${Api.config.apiBaseUrl}/email-accounts/${EmailModule.cache.currentAccount}/emails/images`;
                editor.config.uploadFileName = 'file'; // 后端接收的文件字段名
                editor.config.uploadImgHeaders = {
                    'Authorization': 'Bearer ' + localStorage.getItem('token')
                };
                editor.config.uploadImgHooks = {
                    customInsert: function(insertImg, result, editor) {
                        if (result.success && result.data.url) {
                            // 后端返回的是相对路径，前端直接使用
                            insertImg(result.data.url);
                        } else {
                            layer.msg(result.msg || '上传失败');
                        }
                    }
                };

                editor.create();
                editor.txt.html(body);

                // 初始化附件上传
                EmailModule.initAttachmentUpload();

                // 启动自动保存
                if (EmailModule.draft.saveInterval) {
                    clearInterval(EmailModule.draft.saveInterval);
                }
                EmailModule.draft.saveInterval = setInterval(() => {
                    EmailModule.saveDraft();
                }, 5000); // 5秒自动保存

                // 启动状态更新定时器
                if (EmailModule.draft.statusUpdateInterval) {
                    clearInterval(EmailModule.draft.statusUpdateInterval);
                }
                EmailModule.draft.statusUpdateInterval = setInterval(() => {
                    EmailModule.updateDraftSaveStatus();
                }, 1000); // 每秒更新
            },
            end: function() {
                // 停止自动保存
                if (EmailModule.draft.saveInterval) {
                    clearInterval(EmailModule.draft.saveInterval);
                    EmailModule.draft.saveInterval = null;
                }
                // 停止状态更新
                if (EmailModule.draft.statusUpdateInterval) {
                    clearInterval(EmailModule.draft.statusUpdateInterval);
                    EmailModule.draft.statusUpdateInterval = null;
                }
                EmailModule.draft.current = null;
                EmailModule.draft.lastSaveTime = null;

                if (editor) {
                    editor.destroy();
                    editor = null;
                }
                EmailModule.draft.attachments = []; // 清空附件
            }
        });
    },

    // 初始化附件上传功能
    initAttachmentUpload: function() {
        const self = this;
        
        // 创建隐藏的文件输入框
        let fileInput = document.getElementById('hidden-file-input');
        if (!fileInput) {
            fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.id = 'hidden-file-input';
            fileInput.multiple = true;
            fileInput.style.display = 'none';
            document.body.appendChild(fileInput);
        }

        // 绑定按钮点击事件
        $('#upload-attachment-btn').off('click').on('click', function() {
            fileInput.click();
        });

        // 文件选择变化事件
        $(fileInput).off('change').on('change', function(e) {
            const files = e.target.files;
            if (files.length > 0) {
                for (let i = 0; i < files.length; i++) {
                    self.addAttachment(files[i]);
                }
            }
            // 清空input，允许重复选择同一文件
            fileInput.value = '';
        });
    },

    // 添加附件到列表
    addAttachment: function(file) {
        // 检查文件大小（限制为10MB）
        const maxSize = 10 * 1024 * 1024;
        if (file.size > maxSize) {
            layui.layer.msg('文件大小不能超过10MB');
            return;
        }

        // 添加到附件数组
        this.draft.attachments.push(file);

        // 渲染附件项
        const attachmentItem = $(`
            <div class="attachment-upload-item" data-index="${this.draft.attachments.length - 1}">
                <i class="layui-icon layui-icon-file attachment-icon"></i>
                <div class="attachment-info">
                    <div class="attachment-name">${this.escapeHTML(file.name)}</div>
                    <div class="attachment-size">${this.formatFileSize(file.size)}</div>
                </div>
                <i class="layui-icon layui-icon-close attachment-remove"></i>
            </div>
        `);

        // 绑定删除事件
        attachmentItem.find('.attachment-remove').on('click', () => {
            const index = parseInt(attachmentItem.data('index'));
            this.removeAttachment(index);
        });

        $('#attachment-list').append(attachmentItem);
    },

    // 移除附件
    removeAttachment: function(index) {
        this.draft.attachments.splice(index, 1);
        
        // 重新渲染附件列表
        $('#attachment-list').empty();
        this.draft.attachments.forEach((file, idx) => {
            const attachmentItem = $(`
                <div class="attachment-upload-item" data-index="${idx}">
                    <i class="layui-icon layui-icon-file attachment-icon"></i>
                    <div class="attachment-info">
                        <div class="attachment-name">${this.escapeHTML(file.name)}</div>
                        <div class="attachment-size">${this.formatFileSize(file.size)}</div>
                    </div>
                    <i class="layui-icon layui-icon-close attachment-remove"></i>
                </div>
            `);

            attachmentItem.find('.attachment-remove').on('click', () => {
                this.removeAttachment(idx);
            });

            $('#attachment-list').append(attachmentItem);
        });
    },

    // 格式化文件大小
    formatFileSize: function(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },

    replyEmail: function() {
        if (!this.cache.currentEmail) {
            layui.layer.msg('请先选择一封邮件');
            return;
        }

        formatSender = this.formatSender(this.cache.currentEmail.sender);
        const body = `<br><br><hr>--- 原始邮件 ---<br>发件人: ${formatSender}<br>时间: ${new Date(this.cache.currentEmail.received_date).toLocaleString()}<br>主题: ${this.cache.currentEmail.subject}<br><br>${this.cache.currentEmail.html_content}`;

        this.openComposeModal({
            title: '回复邮件',
            to: this.cache.currentEmail.sender,
            cc: this.cache.currentEmail.cc,
            subject: 'Re: ' + this.cache.currentEmail.subject,
            body: body
        });
    },

    forwardEmail: function() {
        if (!this.cache.currentEmail) {
            layui.layer.msg('请先选择一封邮件');
            return;
        }

        formatSender = this.formatSender(this.cache.currentEmail.sender);
        const body = `<br><br><hr>--- 转发邮件 ---<br>发件人: ${formatSender}<br>时间: ${new Date(this.cache.currentEmail.received_date).toLocaleString()}<br>主题: ${this.cache.currentEmail.subject}<br><br>${this.cache.currentEmail.html_content}`;

        this.openComposeModal({
            title: '转发邮件',
            subject: 'Fwd: ' + this.cache.currentEmail.subject,
            body: body
        });
    },

    deleteEmail: async function(accountId, emailId) {
        // 如果是草稿箱，则调用彻底删除
        if (this.cache.currentFolder === 'Drafts') {
            this.permanentDeleteEmail(accountId, emailId);
            return;
        }

        try {
            await Api.apiRequest(`/email-accounts/${accountId}/emails`, {
                method: 'DELETE',
                body: JSON.stringify({ email_ids: [emailId] })
            });
            layui.layer.msg('删除成功');
            // Remove from DOM
            $(`.email-item[data-email-id='${emailId}']`).remove();
            // Clear detail view
            $('#email-detail-container').html('<div class="placeholder">请选择邮件以查看详情</div>');
        } catch (error) {
            console.error('删除邮件失败:', error);
            layui.layer.msg('删除失败');
        }
    },

    markAsUnread: async function(accountId, emailId) {
        try {
            await Api.apiRequest(`/email-accounts/${accountId}/emails/${emailId}/read?is_read=false`, {
                method: 'PUT'
            });
            layui.layer.msg('标记成功');
            // 更新邮件列表中的状态
            $(`.email-item[data-email-id='${emailId}']`).addClass('unread');
        } catch (error) {
            console.error('标记未读失败:', error);
            layui.layer.msg('标记失败');
        }
    },

    updateDraftSaveStatus: function() {
        if (this.draft.lastSaveTime) {
            const timeAgo = this.formatTimeAgo(this.draft.lastSaveTime);
            $('#draft-save-status').text(`已于 ${timeAgo} 保存`);
        } else {
            $('#draft-save-status').text('');
        }
    },

    saveDraft: async function() {
        const form = $('#compose-email-modal form');
        const to = form.find('#compose-to').val();
        const cc = form.find('#compose-cc').val();
        const subject = form.find('#compose-subject').val();
        const body = editor.txt.html();

        const draftData = {
            id: this.draft.current,
            recipients: to,
            cc: cc,
            subject: subject,
            body: body
        };

        try {
            const response = await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}/drafts`, {
                method: 'POST',
                body: JSON.stringify(draftData)
            });
            // 后端直接返回 { "id": ... }
            if (response && response.id) {
                this.draft.current = response.id;
                this.draft.lastSaveTime = new Date(); // 记录保存时间
                this.updateDraftSaveStatus(); // 立即更新一次
            }
        } catch (error) {
            console.error('保存草稿失败:', error);
        }
    },

    sendEmail: async function(data) {
        const loadingIndex = layui.layer.load(1, { shade: 0.3 });
        
        try {
            // 如果有附件，使用FormData上传
            if (this.draft.attachments.length > 0) {
                const formData = new FormData();
                formData.append('to', data.to);
                if (data.cc) formData.append('cc', data.cc);
                formData.append('subject', data.subject);
                formData.append('body', data.body);
                if (data.draft_id) formData.append('draft_id', data.draft_id);

                // 添加所有附件
                this.draft.attachments.forEach((file, index) => {
                    formData.append('attachments', file);
                });

                // 使用fetch发送FormData
                const token = localStorage.getItem('token');
                const response = await fetch(`${Api.config.apiBaseUrl}/email-accounts/${this.cache.currentAccount}/emails/send`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });

                const result = await response.json();
                if (!result.success) {
                    throw new Error(result.msg || '发送失败');
                }
            } else {
                // 无附件，使用JSON
                await Api.apiRequest(`/email-accounts/${this.cache.currentAccount}/emails/send`, {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
            }

            layui.layer.close(loadingIndex);
            layui.layer.msg('发送成功');
            
            // 停止自动保存
            if (this.draft.saveInterval) {
                clearInterval(this.draft.saveInterval);
                this.draft.saveInterval = null;
            }
            
            // 清空附件
            this.draft.attachments = [];
        } catch (error) {
            layui.layer.close(loadingIndex);
            console.error('发送邮件失败:', error);
            layui.layer.msg('发送失败: ' + error.message);
        }
    },

    permanentDeleteEmail: async function(accountId, emailId) {
        layui.layer.confirm('确定要彻底删除这封邮件吗？此操作不可恢复。', {icon: 3, title:'提示'}, async (index) => {
            try {
                const url = this.cache.currentFolder === 'Drafts'
                    ? `/email-accounts/${accountId}/drafts/${emailId}`
                    : `/email-accounts/${accountId}/emails/${emailId}`;
                await Api.apiRequest(url, {
                    method: 'DELETE'
                });
                layui.layer.msg('彻底删除成功');
                // Remove from DOM
                $(`.email-item[data-email-id='${emailId}']`).remove();
                if (this.cache.currentEmail && this.cache.currentEmail.id === emailId) {
                    $('#email-detail-container').html('<div class="placeholder">请选择邮件以查看详情</div>');
                }
            } catch (error) {
                console.error('彻底删除邮件失败:', error);
                layui.layer.msg('彻底删除失败');
            }
            layui.layer.close(index);
        });
    },

    permanentDeleteSelectedEmails: async function() {
        const selectedIds = this.getSelectedEmailIds();
        if (selectedIds.length === 0) {
            layui.layer.msg('请先选择要彻底删除的邮件');
            return;
        }

        layui.layer.confirm(`确定要彻底删除选中的 ${selectedIds.length} 封邮件吗？此操作不可恢复。`, {icon: 3, title:'提示'}, async (index) => {
            try {
                const url = this.cache.currentFolder === 'Drafts'
                    ? `/email-accounts/${this.cache.currentAccount}/drafts/permanent-delete`
                    : `/email-accounts/${this.cache.currentAccount}/emails/permanent-delete`;
                await Api.apiRequest(url, {
                    method: 'POST',
                    body: JSON.stringify({ email_ids: selectedIds })
                });
                layui.layer.msg('批量彻底删除成功');
                // Remove from DOM
                selectedIds.forEach(id => {
                    $(`.email-item[data-email-id='${id}']`).remove();
                });
                $('#email-detail-container').html('<div class="placeholder">请选择邮件以查看详情</div>');
            } catch (error) {
                console.error('批量彻底删除邮件失败:', error);
                layui.layer.msg('批量彻底删除失败');
            }
            layui.layer.close(index);
        });
    },

    formatTreeData: function(nodes) {
        if (!nodes || nodes.length === 0) {
            return [];
        }
        const treeData = [];
        nodes.forEach(node => {
            if (!(['UNREAD', 'Drafts', 'Sent'].find(f => f === node.name))) {
                const newNode = {
                    title: node.display_name,
                    id: node.name,
                };
                if (node.children && node.children.length > 0) {
                    newNode.children = this.formatTreeData(node.children);
                }
                treeData.push(newNode);
            }
        });
        return treeData;
    },

    moveEmail: async function(accountId, emailId, currentFolder) {
        try {
            // 每次都重新请求文件夹列表
            const folders = await Api.apiRequest(`/email-accounts/${accountId}/folders`);
            if (!folders || folders.length === 0) {
                layui.layer.msg('无法获取文件夹列表');
                return;
            }
            
            const treeData = this.formatTreeData(folders);

            layer.open({
                type: 1,
                title: '选择目标文件夹',
                area: ['400px', 'auto'],
                content: '<div id="folder-tree" class="folder-tree-panel"></div>',
                maxmin: true,
                shadeClose: true,
                success: function(layero, index) {
                    layui.tree.render({
                        elem: '#folder-tree',
                        data: treeData,
                        id: 'folderTree',
                        accordion: true,
                        onlyIconControl: true, // 点击图标展开/折叠
                        click: async function(obj) {
                            const targetFolder = obj.data.id;
                            layer.close(index);

                            try {
                                await Api.apiRequest(`/email-accounts/${accountId}/emails/${emailId}/move`, {
                                    method: 'POST',
                                    body: JSON.stringify({
                                        current_folder: currentFolder,
                                        target_folder: targetFolder
                                    })
                                });
                                layui.layer.msg('移动成功');
                                $(`.email-item[data-email-id='${emailId}']`).remove();
                                if (EmailModule.cache.currentEmail && EmailModule.cache.currentEmail.id === emailId) {
                                    $('#email-detail-container').html('<div class="placeholder">请选择邮件以查看详情</div>');
                                }
                            } catch (error) {
                                console.error('移动邮件失败:', error);
                                layui.layer.msg('移动邮件失败');
                            }
                        }
                    });
                }
            });
        } catch (error) {
            console.error('获取文件夹失败:', error);
            layui.layer.msg('获取文件夹列表失败');
        }
    },

    downloadAttachment: async function(element, filename) {
        const url = $(element).data('url');
        const token = localStorage.getItem('token');
        
        if (!url || !token) {
            layui.layer.msg('下载失败：缺少必要参数');
            return;
        }

        try {
            // 使用fetch API下载文件，携带token
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('下载失败');
            }

            // 获取blob数据
            const blob = await response.blob();
            
            // 创建下载链接
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            a.download = filename;
            
            // 触发下载
            document.body.appendChild(a);
            a.click();
            
            // 清理
            window.URL.revokeObjectURL(downloadUrl);
            document.body.removeChild(a);
            
        } catch (error) {
            console.error('下载附件失败:', error);
            layui.layer.msg('下载附件失败');
        }
    }
};
