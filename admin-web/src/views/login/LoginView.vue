<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  checkEmailPolicy,
  type CaptchaScene,
  type EmailAnalysisResult,
} from '@/api/auth'
import BrandLogo from '@/components/BrandLogo.vue'
import SliderCaptcha from '@/components/SliderCaptcha.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

const publicCfg = computed(() => appStore.publicConfig)
const registrationAllowed = computed(
  () => publicCfg.value.registration_enabled && !publicCfg.value.maintenance_mode,
)

const activeTab = ref<'login' | 'register'>('login')
const submitting = ref(false)

// 弹窗滑动验证
const captchaDialogVisible = ref(false)
const captchaScene = ref<CaptchaScene>('login')

// 登录表单
const loginFormRef = ref<FormInstance>()
const loginForm = reactive({
  account: '',
  password: '',
})

const loginRules: FormRules = {
  account: [{ required: true, message: '请输入邮箱或管理员用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入登录密码', trigger: 'blur' }],
}

// 注册表单
const registerFormRef = ref<FormInstance>()
const emailChecking = ref(false)
const emailCheckResult = ref<EmailAnalysisResult | null>(null)
const registerForm = reactive({
  email: '',
  nickname: '',
  password: '',
  confirmPassword: '',
})

const registerRules: FormRules = {
  email: [{ required: true, message: '请输入正规公共邮箱地址', trigger: 'blur' }],
  password: [
    { required: true, message: '请设置登录密码', trigger: 'blur' },
    { min: 8, message: '密码长度至少为 8 位', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (value && (!/[A-Za-z]/.test(value) || !/\d/.test(value))) {
          callback(new Error('密码需同时包含字母和数字'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (value !== registerForm.password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

const trustPillars = [
  {
    title: '六层正规邮箱风控算法',
    desc: '实时 DNS MX 企业域名邮识别、编辑距离防仿冒与香农熵反批量注册。',
    tag: 'Email Trust',
  },
  {
    title: '7 维行为轨迹防机器人滑块',
    desc: '动态拼图渲染 + 费茨定律速度曲线 + Redis 一次性原子防重放票据。',
    tag: 'Anti-Bot',
  },
  {
    title: '多点在线 & 24 小时自动过期',
    desc: '支持最多 5 端并发在线管理、远程踢下线、登录审计与防爆破锁定。',
    tag: 'Session Guard',
  },
]

async function handleCheckEmail() {
  const email = registerForm.email.trim()
  if (!email || !email.includes('@')) {
    emailCheckResult.value = null
    return
  }
  emailChecking.value = true
  try {
    emailCheckResult.value = await checkEmailPolicy(email)
  } catch {
    emailCheckResult.value = null
  } finally {
    emailChecking.value = false
  }
}

async function submitAuthWithToken(scene: CaptchaScene, captchaToken: string) {
  submitting.value = true
  try {
    if (scene === 'login') {
      const res = await authStore.login(
        loginForm.account.trim(),
        loginForm.password,
        captchaToken,
      )
      captchaDialogVisible.value = false
      ElMessage.success(`欢迎回来，${res.user.nickname}`)
      const isAdmin =
        Boolean(res.user.is_admin_portal) ||
        res.user.role === 'super_admin' ||
        res.user.role === 'admin' ||
        res.user.role === 'operator'
      const redirect =
        typeof route.query.redirect === 'string' &&
        (isAdmin || route.query.redirect === '/profile')
          ? route.query.redirect
          : isAdmin
            ? '/dashboard'
            : '/profile'
      await router.replace(redirect)
    } else {
      const res = await authStore.register({
        email: registerForm.email.trim(),
        password: registerForm.password,
        nickname: registerForm.nickname.trim() || undefined,
        captcha_token: captchaToken,
      })
      captchaDialogVisible.value = false
      ElMessage.success(`注册成功，欢迎加入 ${publicCfg.value.site_name || 'AILOVE'}，${res.user.nickname}`)
      await router.replace('/profile')
    }
  } catch {
    captchaDialogVisible.value = false
  } finally {
    submitting.value = false
  }
}

async function handleOpenLoginCaptcha() {
  const valid = await loginFormRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!publicCfg.value.slider_captcha_enabled) {
    await submitAuthWithToken('login', '')
    return
  }
  captchaScene.value = 'login'
  captchaDialogVisible.value = true
}

async function handleOpenRegisterCaptcha() {
  if (!registrationAllowed.value) {
    ElMessage.warning('当前未开放自助注册，请联系管理员分配账号')
    return
  }
  const valid = await registerFormRef.value?.validate().catch(() => false)
  if (!valid) return

  const normalized = registerForm.email.trim().toLowerCase()
  if (!emailCheckResult.value || emailCheckResult.value.email !== normalized) {
    await handleCheckEmail()
  }
  if (emailCheckResult.value && !emailCheckResult.value.allowed) {
    ElMessage.error(emailCheckResult.value.summary)
    return
  }

  if (!publicCfg.value.slider_captcha_enabled) {
    await submitAuthWithToken('register', '')
    return
  }
  captchaScene.value = 'register'
  captchaDialogVisible.value = true
}

async function handleCaptchaVerified(payload: { token: string; humanScore: number }) {
  await submitAuthWithToken(captchaScene.value, payload.token)
}

onMounted(async () => {
  await appStore.loadPublicConfig()
  if (!registrationAllowed.value) {
    activeTab.value = 'login'
  }
})

function fillDefaultAdmin() {
  activeTab.value = 'login'
  loginForm.account = 'admin'
  loginForm.password = 'Admin123456'
}
</script>

<template>
  <div class="auth-shell">
    <div class="auth-frame">
      <!-- 左侧：温润叙事品牌与风控理念面板 -->
      <section class="brand-panel">
        <div class="ambient-glow glow-rose" />
        <div class="ambient-glow glow-amber" />

        <div class="brand-panel-inner">
          <div class="brand-top">
            <BrandLogo :size="44" />
            <div>
              <div class="wordmark">AILOVE</div>
              <div class="wordmark-sub">Warm Intelligence · Precision Trust</div>
            </div>
          </div>

          <div class="editorial-copy">
            <span class="eyebrow">AI 协同与可信账号中台</span>
            <h1>
              有温度的智能连接，<br />
              从每一次<em>可信验证</em>开始。
            </h1>
            <p class="lead">
              融合情感化交互设计与精密安全风控体系，让真实用户丝滑触达 AI 能力，让异常流量止步门外。
            </p>
          </div>

          <div class="pillar-list">
            <div v-for="item in trustPillars" :key="item.title" class="pillar-card">
              <div class="pillar-head">
                <span class="pillar-title">{{ item.title }}</span>
                <span class="pillar-badge">{{ item.tag }}</span>
              </div>
              <p class="pillar-desc">{{ item.desc }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 右侧：极净交互登录 / 注册表单区 -->
      <section class="form-panel">
        <div class="mobile-brand">
          <BrandLogo :size="36" />
          <span class="mobile-wordmark">AILOVE</span>
        </div>

        <div class="form-head">
          <h2>{{ activeTab === 'login' ? `欢迎回到 ${publicCfg.site_name || 'AILOVE'}` : `创建你的 ${publicCfg.site_name || 'AILOVE'} 账号` }}</h2>
          <p>
            {{
              activeTab === 'login'
                ? '使用注册邮箱或管理员账号登录，支持多点会话与安全审计守护'
                : '仅支持正规公共邮箱注册，点击提交后完成拼图滑动验证'
            }}
          </p>
        </div>

        <el-alert
          v-if="publicCfg.maintenance_mode"
          title="系统当前正处于维护模式，暂仅限管理角色登录，已暂停新用户注册。"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom: 16px"
        />

        <!-- 精致胶囊分段切换器 -->
        <div class="segmented-switch" role="tablist">
          <button
            type="button"
            role="tab"
            :aria-selected="activeTab === 'login'"
            class="seg-btn"
            :class="{ 'is-active': activeTab === 'login' }"
            @click="activeTab = 'login'"
          >
            账号登录
          </button>
          <button
            v-if="registrationAllowed"
            type="button"
            role="tab"
            :aria-selected="activeTab === 'register'"
            class="seg-btn"
            :class="{ 'is-active': activeTab === 'register' }"
            @click="activeTab = 'register'"
          >
            邮箱注册
          </button>
        </div>

        <!-- 登录表单 -->
        <el-form
          v-if="activeTab === 'login'"
          ref="loginFormRef"
          :model="loginForm"
          :rules="loginRules"
          label-position="top"
          size="large"
          class="auth-form"
          @submit.prevent="handleOpenLoginCaptcha"
        >
          <el-form-item label="邮箱 / 用户名" prop="account">
            <el-input
              v-model="loginForm.account"
              placeholder="请输入注册邮箱或管理员用户名"
              prefix-icon="User"
              clearable
            />
          </el-form-item>

          <el-form-item label="登录密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              show-password
              placeholder="请输入登录密码"
              prefix-icon="Lock"
            />
          </el-form-item>

          <el-button
            type="primary"
            native-type="submit"
            :loading="submitting"
            class="submit-btn"
          >
            立即登录
          </el-button>

          <div class="auth-footer-hint">
            <span>管理员演示账号：<code>admin</code> / <code>Admin123456</code></span>
            <el-button link type="primary" size="small" @click="fillDefaultAdmin">
              一键填充
            </el-button>
          </div>
        </el-form>

        <!-- 邮箱注册表单 -->
        <el-form
          v-else
          ref="registerFormRef"
          :model="registerForm"
          :rules="registerRules"
          label-position="top"
          size="default"
          class="auth-form"
          @submit.prevent="handleOpenRegisterCaptcha"
        >
          <el-form-item label="正规个人邮箱" prop="email">
            <el-input
              v-model="registerForm.email"
              placeholder="支持 QQ / 163 / 126 / Gmail / Outlook / iCloud"
              prefix-icon="Message"
              clearable
              @blur="handleCheckEmail"
            >
              <template #append>
                <el-button :loading="emailChecking" @click="handleCheckEmail">检测</el-button>
              </template>
            </el-input>
          </el-form-item>

          <div
            v-if="emailCheckResult"
            class="email-check-card"
            :class="emailCheckResult.allowed ? 'is-ok' : 'is-blocked'"
          >
            <div class="check-row">
              <span class="check-status">
                {{ emailCheckResult.allowed ? '正规邮箱验证通过' : '已被邮箱风控算法拦截' }}
              </span>
              <span class="check-score mono-num">
                {{ emailCheckResult.provider }} · {{ emailCheckResult.trust_score }}分
              </span>
            </div>
            <div class="check-desc">{{ emailCheckResult.summary }}</div>
          </div>

          <el-form-item label="显示昵称（可选）" prop="nickname">
            <el-input
              v-model="registerForm.nickname"
              placeholder="留空默认使用邮箱前缀"
              prefix-icon="User"
              maxlength="32"
            />
          </el-form-item>

          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="设置密码" prop="password">
                <el-input
                  v-model="registerForm.password"
                  type="password"
                  show-password
                  placeholder="至少 8 位含字母数字"
                  prefix-icon="Lock"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="确认密码" prop="confirmPassword">
                <el-input
                  v-model="registerForm.confirmPassword"
                  type="password"
                  show-password
                  placeholder="再次输入密码"
                  prefix-icon="Lock"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-button
            type="primary"
            native-type="submit"
            :loading="submitting || emailChecking"
            :disabled="emailCheckResult !== null && !emailCheckResult.allowed"
            class="submit-btn"
          >
            立即注册
          </el-button>
        </el-form>
      </section>
    </div>

    <!-- 点击登录/注册后触发的拼图滑块验证弹窗 -->
    <el-dialog
      v-model="captchaDialogVisible"
      :title="captchaScene === 'login' ? '登录安全验证' : '注册安全验证'"
      width="376px"
      align-center
      destroy-on-close
      :close-on-click-modal="false"
    >
      <div
        v-loading="submitting"
        element-loading-text="人机验证通过，正在安全提交..."
        class="dialog-captcha"
      >
        <p class="dialog-tip">拖动拼图对齐缺口，通过行为轨迹检测后自动继续</p>
        <SliderCaptcha
          v-if="captchaDialogVisible"
          :scene="captchaScene"
          @verified="handleCaptchaVerified"
        />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px 20px;
  background:
    radial-gradient(circle at 12% 14%, rgba(225, 75, 104, 0.08), transparent 40%),
    radial-gradient(circle at 88% 82%, rgba(217, 119, 6, 0.08), transparent 42%),
    var(--ailove-canvas);
}

.auth-frame {
  width: 100%;
  max-width: 1020px;
  min-height: 610px;
  display: grid;
  grid-template-columns: 1.06fr 1fr;
  background: var(--ailove-surface);
  border-radius: var(--ailove-radius-xl);
  border: 1px solid var(--ailove-border);
  box-shadow: var(--ailove-shadow-elevated);
  overflow: hidden;
}

/* 左侧暖黑曜石品牌叙事面板 */
.brand-panel {
  position: relative;
  background: linear-gradient(155deg, #211924 0%, #17121a 60%, #24171d 100%);
  color: #faf7f5;
  padding: 40px 38px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
}

.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(68px);
  pointer-events: none;
}

.glow-rose {
  width: 280px;
  height: 280px;
  background: rgba(225, 75, 104, 0.28);
  top: -70px;
  right: -60px;
}

.glow-amber {
  width: 240px;
  height: 240px;
  background: rgba(217, 119, 6, 0.2);
  bottom: -60px;
  left: -40px;
}

.brand-panel-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  justify-content: space-between;
  gap: 28px;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 14px;
}

.wordmark {
  font-family: var(--ailove-font-display);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #ffffff;
}

.wordmark-sub {
  font-size: 11.5px;
  color: rgba(250, 247, 245, 0.6);
  letter-spacing: 0.04em;
  margin-top: 2px;
}

.eyebrow {
  display: inline-block;
  font-size: 11.5px;
  font-weight: 500;
  color: #fec3d2;
  background: rgba(225, 75, 104, 0.16);
  border: 1px solid rgba(254, 195, 210, 0.24);
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 16px;
}

.editorial-copy h1 {
  margin: 0 0 14px;
  font-family: var(--ailove-font-display);
  font-size: 29px;
  font-weight: 700;
  line-height: 1.32;
  letter-spacing: -0.02em;
  color: #ffffff;
}

.editorial-copy h1 em {
  font-style: normal;
  background: linear-gradient(90deg, #ff8ba0, #fbbf24);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.lead {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: rgba(250, 247, 245, 0.72);
}

.pillar-list {
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.pillar-card {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 12px;
  padding: 12px 14px;
  backdrop-filter: blur(8px);
}

.pillar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.pillar-title {
  font-size: 13px;
  font-weight: 600;
  color: #ffffff;
}

.pillar-badge {
  font-family: var(--ailove-font-mono);
  font-size: 10.5px;
  color: #fec3d2;
  background: rgba(225, 75, 104, 0.18);
  padding: 2px 8px;
  border-radius: 999px;
}

.pillar-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: rgba(250, 247, 245, 0.65);
}

/* 右侧表单区 */
.form-panel {
  padding: 42px 44px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.mobile-brand {
  display: none;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.mobile-wordmark {
  font-family: var(--ailove-font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.form-head h2 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ailove-ink-primary);
}

.form-head p {
  margin: 8px 0 22px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ailove-ink-muted);
}

.segmented-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  background: var(--ailove-canvas);
  border: 1px solid var(--ailove-border);
  border-radius: 12px;
  margin-bottom: 22px;
}

.seg-btn {
  border: none;
  background: transparent;
  padding: 9px 12px;
  border-radius: 9px;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--ailove-ink-secondary);
  cursor: pointer;
  transition: all 0.18s var(--ailove-ease);
}

.seg-btn.is-active {
  background: #ffffff;
  color: var(--ailove-brand-600);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(26, 22, 29, 0.08);
}

.auth-form :deep(.el-form-item__label) {
  font-weight: 500;
  font-size: 13px;
  color: var(--ailove-ink-secondary);
  padding-bottom: 6px;
}

.email-check-card {
  margin: -6px 0 14px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.5;
}

.email-check-card.is-ok {
  background: var(--ailove-success-bg);
  border: 1px solid var(--ailove-success-border);
  color: #065f46;
}

.email-check-card.is-blocked {
  background: var(--ailove-danger-bg);
  border: 1px solid var(--ailove-danger-border);
  color: var(--ailove-danger);
}

.check-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 3px;
}

.check-status {
  font-weight: 600;
}

.check-score {
  font-size: 11.5px;
  font-weight: 600;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  border-radius: 10px;
  margin-top: 8px;
}

.auth-footer-hint {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--ailove-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.auth-footer-hint code {
  font-family: var(--ailove-font-mono);
  background: var(--ailove-canvas);
  padding: 2px 6px;
  border-radius: 5px;
  color: var(--ailove-ink-primary);
}

.dialog-captcha {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2px 0 8px;
}

.dialog-tip {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--ailove-ink-muted);
  text-align: center;
}

@media (max-width: 900px) {
  .auth-frame {
    grid-template-columns: 1fr;
    max-width: 460px;
    min-height: auto;
  }

  .brand-panel {
    display: none;
  }

  .mobile-brand {
    display: flex;
  }

  .form-panel {
    padding: 30px 24px 26px;
  }
}
</style>
