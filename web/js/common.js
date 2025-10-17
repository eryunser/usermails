const $ = layui.$;

function escapeHtml (str) {
    if (!str) return ''; // 处理空值
    return str.toString()
        .replace(/&/g, '&amp;')  // 转义 &
        .replace(/</g, '&lt;')   // 转义 <
        .replace(/>/g, '&gt;')   // 转义 >
        .replace(/"/g, '&quot;') // 转义 "
        .replace(/'/g, '&#39;'); // 转义 '
};