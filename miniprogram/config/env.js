/**
 * 环境配置：
 * - 本地私有云端地址请复制 env.local.example.js 为 env.local.js（已加入 .gitignore，不提交至 Git）
 * - 本地开发请在微信开发者工具中勾选「不校验合法域名、web-view、TLS 版本以及 HTTPS 证书」
 */
let localOverrides = null
try {
  // 仅读取本地私有覆盖文件（已 gitignore），避免在公开仓库暴露个人服务器 IP
  localOverrides = require('./env.local')
} catch (_e) {
  localOverrides = null
}

const ENV_PRESETS = {
  cloud: {
    ENV: 'cloud',
    LABEL: '云端测试服',
    API_BASE_URL:
      (localOverrides && localOverrides.CLOUD_API_BASE_URL) ||
      'https://your-test-server.example.com/api/v1',
  },
  local: {
    ENV: 'local',
    LABEL: '本机开发服',
    API_BASE_URL:
      (localOverrides && localOverrides.LOCAL_API_BASE_URL) || 'http://127.0.0.1:8000/api/v1',
  },
  production: {
    ENV: 'production',
    LABEL: '正式生产服',
    API_BASE_URL:
      (localOverrides && localOverrides.PROD_API_BASE_URL) || 'https://api.example.com/api/v1',
  },
}

const DEFAULT_ENV =
  localOverrides && localOverrides.CLOUD_API_BASE_URL ? 'cloud' : 'local'
const OVERRIDE_KEY = 'ailove_env_override'

function getEnvConfig() {
  try {
    const saved = wx.getStorageSync(OVERRIDE_KEY)
    if (saved && ENV_PRESETS[saved]) {
      return ENV_PRESETS[saved]
    }
  } catch (_e) {
    // 忽略存储读取异常
  }
  return ENV_PRESETS[DEFAULT_ENV]
}

function setEnvOverride(envKey) {
  if (!ENV_PRESETS[envKey]) return getEnvConfig()
  wx.setStorageSync(OVERRIDE_KEY, envKey)
  return ENV_PRESETS[envKey]
}

module.exports = {
  ENV_PRESETS,
  DEFAULT_ENV,
  getEnvConfig,
  setEnvOverride,
}
