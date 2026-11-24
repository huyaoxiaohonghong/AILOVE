<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '@/plugins/element-plus'
import { exportAiUsageCsv, fetchAiAnalytics, type AIAnalyticsData } from '@/api/ai'
import { fetchDashboardOverview, type DashboardOverview } from '@/api/system'

const loading = ref(false)
const exportingCsv = ref(false)
const overview = ref<DashboardOverview | null>(null)
const analytics = ref<AIAnalyticsData | null>(null)
const analyticsDays = ref(7)
const chartMetric = ref<'requests' | 'tokens'>('requests')
const hoveredIndex = ref<number | null>(null)

async function loadOverview() {
  loading.value = true
  try {
    const [ov, aiStats] = await Promise.all([
      fetchDashboardOverview(),
      fetchAiAnalytics(analyticsDays.value).catch(() => null),
    ])
    overview.value = ov
    analytics.value = aiStats
  } finally {
    loading.value = false
  }
}

async function switchDays(days: number) {
  if (analyticsDays.value === days) return
  analyticsDays.value = days
  hoveredIndex.value = null
  analytics.value = await fetchAiAnalytics(days).catch(() => analytics.value)
}

async function handleExportAiCsv() {
  exportingCsv.value = true
  try {
    const filename = await exportAiUsageCsv(analyticsDays.value)
    ElMessage.success(`已导出 ${filename}`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '导出失败')
  } finally {
    exportingCsv.value = false
  }
}

const SVG_W = 640
const SVG_H = 210
const PAD_L = 50
const PAD_R = 16
const PAD_T = 18
const PAD_B = 30

function formatAxisTick(val: number): string {
  if (val >= 10000) return `${Math.round(val / 1000)}k`
  if (val >= 1000) return `${(val / 1000).toFixed(1)}k`
  return String(val)
}

const chartGeometry = computed(() => {
  const rows = analytics.value?.daily_trend ?? []
  const values = rows.map((r) => (chartMetric.value === 'requests' ? r.requests : r.tokens))
  const rawMax = Math.max(0, ...values)
  const maxVal = rawMax <= 0 ? 4 : Math.ceil(rawMax * 1.18)
  const plotW = SVG_W - PAD_L - PAD_R
  const plotH = SVG_H - PAD_T - PAD_B
  const n = Math.max(1, rows.length)

  const points = rows.map((row, idx) => {
    const val = chartMetric.value === 'requests' ? row.requests : row.tokens
    const x = n === 1 ? PAD_L + plotW / 2 : PAD_L + (idx * plotW) / (n - 1)
    const y = PAD_T + plotH - (val / maxVal) * plotH
    return {
      ...row,
      value: val,
      x: Number(x.toFixed(1)),
      y: Number(y.toFixed(1)),
    }
  })

  const polyline = points.map((p) => `${p.x},${p.y}`).join(' ')
  const areaPath =
    points.length > 0
      ? `M ${points[0].x},${PAD_T + plotH} ` +
        points.map((p) => `L ${p.x},${p.y}`).join(' ') +
        ` L ${points[points.length - 1].x},${PAD_T + plotH} Z`
      : ''

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: Number((PAD_T + plotH * (1 - ratio)).toFixed(1)),
    label: formatAxisTick(Math.round(maxVal * ratio)),
  }))

  return { points, polyline, areaPath, yTicks, baselineY: PAD_T + plotH }
})

const activePoint = computed(() => {
  const pts = chartGeometry.value.points
  if (!pts.length) return null
  if (hoveredIndex.value !== null && pts[hoveredIndex.value]) {
    return pts[hoveredIndex.value]
  }
  return pts[pts.length - 1]
})

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

    <el-row v-if="analytics" :gutter="18" class="analytics-row">
      <el-col :xs="24" :lg="15">
        <div class="page-card chart-card">
          <div class="card-head chart-head">
            <div>
              <h3 class="section-title">AI 用量趋势洞察</h3>
              <p class="section-sub">
                近 {{ analytics.days }} 天累计
                <strong class="mono-num">{{ analytics.summary.total_requests }}</strong> 次调用 ·
                <strong class="mono-num">{{ analytics.summary.total_tokens.toLocaleString() }}</strong> Tokens ·
                均值 <strong class="mono-num">{{ analytics.summary.avg_latency_ms }}ms</strong>
              </p>
            </div>
            <div class="chart-controls">
              <div class="seg-group">
                <button
                  type="button"
                  class="seg-btn"
                  :class="{ 'is-active': chartMetric === 'requests' }"
                  @click="chartMetric = 'requests'"
                >
                  调用次数
                </button>
                <button
                  type="button"
                  class="seg-btn"
                  :class="{ 'is-active': chartMetric === 'tokens' }"
                  @click="chartMetric = 'tokens'"
                >
                  Token 量
                </button>
              </div>
              <div class="seg-group">
                <button
                  type="button"
                  class="seg-btn"
                  :class="{ 'is-active': analyticsDays === 7 }"
                  @click="switchDays(7)"
                >
                  7 天
                </button>
                <button
                  type="button"
                  class="seg-btn"
                  :class="{ 'is-active': analyticsDays === 14 }"
                  @click="switchDays(14)"
                >
                  14 天
                </button>
              </div>
              <el-button
                size="small"
                plain
                icon="Document"
                :loading="exportingCsv"
                @click="handleExportAiCsv"
              >
                导出 CSV
              </el-button>
            </div>
          </div>

          <div class="ai-mini-kpis mono-num">
            <div class="mini-kpi">
              <span class="mini-label">今日调用</span>
              <strong>{{ analytics.summary.today_requests }}</strong>
            </div>
            <div class="mini-kpi">
              <span class="mini-label">今日 Token</span>
              <strong>{{ analytics.summary.today_tokens.toLocaleString() }}</strong>
            </div>
            <div class="mini-kpi">
              <span class="mini-label">活跃 AI 用户</span>
              <strong>{{ analytics.summary.active_users }}</strong>
            </div>
            <div class="mini-kpi">
              <span class="mini-label">成功 / 异常</span>
              <strong>{{ analytics.summary.success_requests }} / {{ analytics.summary.failed_requests }}</strong>
            </div>
          </div>

          <div v-if="activePoint" class="active-point-strip mono-num">
            <span>{{ activePoint.date }}</span>
            <span>调用 <strong>{{ activePoint.requests }}</strong> 次</span>
            <span>Token <strong>{{ activePoint.tokens.toLocaleString() }}</strong></span>
            <span>平均延迟 <strong>{{ activePoint.avg_latency_ms }}ms</strong></span>
          </div>

          <div class="svg-wrap">
            <svg :viewBox="`0 0 ${SVG_W} ${SVG_H}`" class="trend-svg" role="img" aria-label="AI 调用趋势图">
              <defs>
                <linearGradient id="ailoveTrendGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#E14B68" stop-opacity="0.28" />
                  <stop offset="100%" stop-color="#E14B68" stop-opacity="0.02" />
                </linearGradient>
              </defs>

              <g v-for="tick in chartGeometry.yTicks" :key="tick.y">
                <line
                  :x1="PAD_L"
                  :y1="tick.y"
                  :x2="SVG_W - PAD_R"
                  :y2="tick.y"
                  stroke="#EAE2D8"
                  stroke-dasharray="3 3"
                />
                <text :x="PAD_L - 8" :y="tick.y + 4" text-anchor="end" class="axis-text">
                  {{ tick.label }}
                </text>
              </g>

              <path v-if="chartGeometry.areaPath" :d="chartGeometry.areaPath" fill="url(#ailoveTrendGrad)" />
              <polyline
                v-if="chartGeometry.polyline"
                :points="chartGeometry.polyline"
                fill="none"
                stroke="#C83553"
                stroke-width="2.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              />

              <g v-for="(pt, idx) in chartGeometry.points" :key="pt.date">
                <circle
                  :cx="pt.x"
                  :cy="pt.y"
                  :r="hoveredIndex === idx ? 5.5 : 3.5"
                  :fill="hoveredIndex === idx ? '#C83553' : '#FFFFFF'"
                  stroke="#C83553"
                  stroke-width="2"
                  class="trend-dot"
                  @mouseenter="hoveredIndex = idx"
                  @mouseleave="hoveredIndex = null"
                >
                  <title>{{ `${pt.date}: ${pt.requests} 次 / ${pt.tokens} tokens` }}</title>
                </circle>
                <text
                  v-if="analytics.days <= 7 || idx % 2 === 0 || idx === chartGeometry.points.length - 1"
                  :x="pt.x"
                  :y="SVG_H - 8"
                  text-anchor="middle"
                  class="axis-text"
                >
                  {{ pt.label }}
                </text>
              </g>
            </svg>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :lg="9">
        <div class="page-card breakdown-card">
          <div class="card-head">
            <h3 class="section-title">模型分布 & 热门智能体</h3>
            <span class="pill-live mono-num">Top 5</span>
          </div>

          <div class="sub-block">
            <div class="sub-block-title">模型调用占比</div>
            <div v-if="analytics.by_model.length === 0" class="empty-mini">暂无调用样本</div>
            <div v-for="m in analytics.by_model" :key="`${m.provider}-${m.model_name}`" class="bar-item">
              <div class="bar-meta">
                <span class="bar-name">{{ m.model_name }}</span>
                <span class="bar-stat mono-num">{{ m.requests }} 次 ({{ m.share_percent }}%)</span>
              </div>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${Math.max(4, m.share_percent)}%` }" />
              </div>
            </div>
          </div>

          <div class="sub-block">
            <div class="sub-block-title">热门智能体排行</div>
            <div v-if="analytics.top_personas.length === 0" class="empty-mini">暂无智能体记录</div>
            <div v-for="(p, i) in analytics.top_personas" :key="`${p.persona_id}-${i}`" class="rank-row">
              <span class="rank-idx mono-num">{{ i + 1 }}</span>
              <span class="rank-name">{{ p.persona_name }}</span>
              <span class="rank-val mono-num">{{ p.requests }} 次</span>
            </div>
          </div>

          <div class="sub-block">
            <div class="sub-block-title">活跃调用成员</div>
            <div v-if="analytics.top_users.length === 0" class="empty-mini">暂无活跃调用用户</div>
            <div v-for="(u, i) in analytics.top_users" :key="u.owner_scope" class="rank-row">
              <span class="rank-idx is-amber mono-num">{{ i + 1 }}</span>
              <span class="rank-name">{{ u.username }}</span>
              <span class="rank-val mono-num">
                {{ u.requests }} 次 · {{ u.tokens.toLocaleString() }} tok
              </span>
            </div>
          </div>
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

.analytics-row {
  margin-bottom: 18px;
}

.chart-card,
.breakdown-card {
  margin-bottom: 14px;
}

.chart-head {
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}

.section-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ailove-ink-muted);
}

.chart-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.seg-group {
  display: inline-flex;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  border-radius: 8px;
  padding: 2px;
}

.seg-btn {
  border: none;
  background: transparent;
  color: var(--ailove-ink-secondary);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.seg-btn.is-active {
  background: var(--ailove-surface);
  color: var(--ailove-brand-600);
  box-shadow: 0 1px 2px rgba(26, 22, 29, 0.08);
}

.ai-mini-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.mini-kpi {
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mini-label {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.mini-kpi strong {
  font-size: 16px;
  color: var(--ailove-ink-primary);
}

.active-point-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: var(--ailove-ink-secondary);
  padding: 6px 10px;
  background: var(--ailove-brand-50);
  border-radius: 8px;
  margin-bottom: 8px;
}

.svg-wrap {
  width: 100%;
}

.trend-svg {
  width: 100%;
  height: auto;
  display: block;
}

.axis-text {
  font-size: 11px;
  fill: #847b89;
  font-variant-numeric: tabular-nums;
}

.trend-dot {
  cursor: pointer;
  transition: r 0.15s;
}

.sub-block + .sub-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--ailove-border);
}

.sub-block-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ailove-ink-secondary);
  margin-bottom: 8px;
}

.empty-mini {
  font-size: 12.5px;
  color: var(--ailove-ink-muted);
  padding: 4px 0;
}

.bar-item + .bar-item {
  margin-top: 8px;
}

.bar-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  margin-bottom: 4px;
}

.bar-name {
  color: var(--ailove-ink-primary);
  font-weight: 500;
}

.bar-stat {
  color: var(--ailove-ink-muted);
}

.bar-track {
  height: 7px;
  border-radius: 999px;
  background: var(--ailove-subtle);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #e14b68 0%, #c83553 100%);
}

.rank-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  padding: 5px 0;
}

.rank-idx {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  font-weight: 600;
  font-size: 11.5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.rank-idx.is-amber {
  background: var(--ailove-accent-amber-bg);
  color: var(--ailove-accent-amber);
}

.rank-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ailove-ink-primary);
}

.rank-val {
  color: var(--ailove-ink-muted);
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .ai-mini-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
