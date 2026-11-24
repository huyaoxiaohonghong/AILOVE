/**
 * 本地私有环境覆盖模板：
 * 复制为同目录 env.local.js 后填入你的云端测试服地址（env.local.js 已被 .gitignore 忽略）
 */
module.exports = {
  CLOUD_API_BASE_URL: 'http://YOUR_SERVER_IP:PORT/api/v1',
  LOCAL_API_BASE_URL: 'http://127.0.0.1:8000/api/v1',
  PROD_API_BASE_URL: 'https://api.example.com/api/v1',
}
