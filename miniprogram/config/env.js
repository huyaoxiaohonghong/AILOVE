/**
 * 环境配置：
 * - 本地开发请在微信开发者工具中勾选「不校验合法域名、web-view、TLS 版本以及 HTTPS 证书」
 * - 生产发布前请替换为已备案的 HTTPS 正式域名
 */
const ENV_CONFIG = {
  development: {
    ENV: 'development',
    API_BASE_URL: 'http://127.0.0.1:8000/api/v1',
  },
  production: {
    ENV: 'production',
    API_BASE_URL: 'https://api.example.com/api/v1',
  },
}

const CURRENT_ENV = 'development'

module.exports = ENV_CONFIG[CURRENT_ENV]
