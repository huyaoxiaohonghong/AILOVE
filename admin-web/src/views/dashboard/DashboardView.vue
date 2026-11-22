<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchDashboardOverview, type DashboardOverview } from '@/api/system'

const loading = ref(false)
const overview = ref<DashboardOverview | null>(null)

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await fetchDashboardOverview()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadOverview()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统控制台</h2>
        <p class="page-subtitle">实时洞察平台账号生态、多端会话在线状态与底层基础设施健康度</p>
      </div>
      <el-button type="primary" plain icon="Refresh" @click="loadOverview">刷新状态</el-button>
    </div>

    <el-alert
      v-if="overview && !overview.stats.db_connected"
      title="当前 MySQL 尚未连接，仪表盘以骨架降级模式展示。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 18px"
    />

    <el-row :gutter="18" class="kpi-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <div class="kpi-top">
            <span class="kpi-label">平台账号总数</span>
            <div class="kpi-icon is-rose">
              <el-icon><UserFilled /></el-icon>
            </div>
          </div>
          <div class="kpi-value mono-num">{{ overview?.stats.platform_user_count ?? 1 }}</div>
          <div class="kpi-foot">含管理员与全部活跃成员</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <div class="kpi-top">
            <span class="kpi-label">邮箱自助注册数</span>
            <div class="kpi-icon is-emerald">
              <el-icon><Message /></el-icon>
            </div>
          </div>
          <div class="kpi-value mono-num">{{ overview?.stats.email_registered_count ?? 0 }}</div>
          <div class="kpi-foot">已通过六层正规邮箱风控算法</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <div class="kpi-top">
            <span class="kpi-label">管理员分配账号</span>
            <div class="kpi-icon is-amber">
              <el-icon><Key /></el-icon>
            </div>
          </div>
          <div class="kpi-value mono-num">{{ overview?.stats.admin_assigned_count ?? 0 }}</div>
          <div class="kpi-foot">后台受控分配创建</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <div class="kpi-top">
            <span class="kpi-label">多端在线会话数</span>
            <div class="kpi-icon is-slate">
              <el-icon><Monitor /></el-icon>
            </div>
          </div>
          <div class="kpi-value mono-num">{{ overview?.stats.active_session_count ?? 0 }}</div>
          <div class="kpi-foot">Redis 24 小时活跃会话池</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="18">
      <el-col :xs="24" :lg="12">
        <div class="page-card">
          <div class="card-head">
            <h3 class="section-title">基础设施健康状态</h3>
            <span class="pill-live">
              <span
                class="status-dot"
                :class="
                  overview?.services.mysql.healthy && overview?.services.redis.healthy
                    ? 'is-live'
                    : 'is-warn'
                "
              />
              {{
                overview?.services.mysql.healthy && overview?.services.redis.healthy
                  ? '全链路健康'
                  : '部分降级'
              }}
            </span>
          </div>

          <div class="service-list">
            <div class="service-row">
              <div class="service-info">
                <span
                  class="status-dot"
                  :class="overview?.services.mysql.healthy ? 'is-live' : 'is-off'"
                />
                <span>MySQL 8.0 主数据库</span>
              </div>
              <el-tag :type="overview?.services.mysql.healthy ? 'success' : 'danger'" size="small">
                {{ overview?.services.mysql.status || '检测中' }}
              </el-tag>
            </div>

            <div class="service-row">
              <div class="service-info">
                <span
                  class="status-dot"
                  :class="overview?.services.redis.healthy ? 'is-live' : 'is-warn'"
                />
                <span>Redis 7 会话 / 滑块缓存</span>
              </div>
              <el-tag :type="overview?.services.redis.healthy ? 'success' : 'warning'" size="small">
                {{ overview?.services.redis.status || '检测中' }}
              </el-tag>
            </div>

            <div class="service-row">
              <div class="service-info">
                <span
                  class="status-dot"
                  :class="overview?.services.langchain.configured ? 'is-live' : 'is-warn'"
                />
                <span>LangChain 大模型引擎</span>
              </div>
              <el-tag
                :type="overview?.services.langchain.configured ? 'success' : 'info'"
                size="small"
              >
                {{ overview?.services.langchain.configured ? '已配置 API Key' : '演示模式' }}
              </el-tag>
            </div>

            <div class="service-row">
              <div class="service-info">
                <span
                  class="status-dot"
                  :class="overview?.services.wechat.configured ? 'is-live' : 'is-warn'"
                />
                <span>微信小程序登录凭据</span>
              </div>
              <el-tag
                :type="overview?.services.wechat.configured ? 'success' : 'info'"
                size="small"
              >
                {{ overview?.services.wechat.configured ? '已配置' : '待配置' }}
              </el-tag>
            </div>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="page-card">
          <div class="card-head">
            <h3 class="section-title">LangChain 运行参数与接口文档</h3>
          </div>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="Provider / 协议">
              <span class="mono-num">
                {{ overview?.services.langchain.provider || '-' }}
                <template v-if="overview?.services.langchain.protocol">
                  ({{ overview.services.langchain.protocol }})
                </template>
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="当前模型">
              <span class="mono-num">{{ overview?.services.langchain.model || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Base URL">
              <span class="mono-num">{{ overview?.services.langchain.base_url || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="OpenAPI 文档">
              <a href="/docs" target="_blank" rel="noreferrer">打开 Swagger API 文档 (/docs) ↗</a>
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.kpi-row {
  margin-bottom: 18px;
}

.kpi-card {
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  border-radius: var(--ailove-radius-lg);
  box-shadow: var(--ailove-shadow-card);
  padding: 20px;
  margin-bottom: 14px;
  transition: transform 0.2s var(--ailove-ease), border-color 0.2s;
}

.kpi-card:hover {
  transform: translateY(-2px);
  border-color: var(--ailove-brand-200);
}

.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kpi-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--ailove-ink-secondary);
}

.kpi-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
}

.kpi-icon.is-rose {
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
}

.kpi-icon.is-emerald {
  background: var(--ailove-success-bg);
  color: var(--ailove-success);
}

.kpi-icon.is-amber {
  background: var(--ailove-accent-amber-bg);
  color: var(--ailove-accent-amber);
}

.kpi-icon.is-slate {
  background: var(--ailove-info-bg);
  color: var(--ailove-info);
}

.kpi-value {
  margin-top: 12px;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ailove-ink-primary);
}

.kpi-foot {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-title {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.pill-live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ailove-ink-secondary);
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  padding: 4px 10px;
  border-radius: 999px;
}

.service-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.service-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  font-size: 13.5px;
  color: var(--ailove-ink-primary);
}

.service-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 500;
}
</style>
