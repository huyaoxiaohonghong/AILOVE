# AILOVE Design System — MASTER Specification (UI UX Pro Max)

> **Single Source of Truth**：本规范基于 **UI UX Pro Max** 设计系统方法论构建，定义 AILOVE 网站管理端、用户账号中心及未来微信小程序的统一视觉语言、语义色彩、排版阶梯、组件规则与无障碍红线。

---

## 1. 领域分析与品牌中心思想（Domain & Brand Philosophy）

- **产品定位**：**AILOVE**（有温度的 AI 协同与情感陪伴平台 + 高可信度企业级管理与风控中台）。
- **双核心基因**：
  1. **温润连接（Human Warmth / Love）**：抛弃传统后台冰冷僵硬的蓝黑工控感与廉价“AI 霓虹紫粉渐变”，采用温润的**暖白羊皮纸画布（Warm Alabaster）**与极具生命力的**玫瑰珊瑚红（Rose-Coral）**作为品牌识别色，传达真诚、善意与陪伴感。
  2. **精密信任（Precision & Security）**：面向账号风控（六层正规邮箱识别、7 维行为轨迹防机器人滑块、24h 多点会话治理），通过 **1px 精致发丝边框、清晰卡片层级、高对比深墨文字、等宽数字对齐（tabular-nums）与实时状态脉动指示灯** 传达专业、可靠与可控感。
- **风格命名**：**Warm Editorial SaaS × Precision Trust Console**（温润叙事美学 × 精密信任控制台）
- **设计参数**：`density: balanced` · `motion: crisp-spring` · `surface: daylight-warm` · `contrast: WCAG AA/AAA`

---

## 2. 语义色彩系统（Semantic Color Palette）

### 2.1 画布与表面层级（Warm Daylight Surfaces）
| Token | Hex | 用途 |
| --- | --- | --- |
| `--bg-canvas` | `#F7F4F1` | 全局主背景画布（暖米丝绸底，长时办公护眼） |
| `--bg-subtle` | `#FBF9F7` | 侧边栏与次级区块底色 |
| `--bg-surface` | `#FFFFFF` | 卡片、弹窗、表格主体悬浮面 |
| `--bg-surface-hover` | `#FAF7F5` | 表格行、菜单项与可交互容器悬浮面 |
| `--border-hairline` | `rgba(24, 20, 26, 0.08)` | 1px 精致卡片与分割线边框 |
| `--border-strong` | `rgba(24, 20, 26, 0.14)` | 输入框、按钮默认描边 |

### 2.2 文字与墨色阶梯（Warm Obsidian Ink）
| Token | Hex | 对比度（白底） | 用途 |
| --- | --- | --- | --- |
| `--ink-primary` | `#1A161D` | 17.5:1 (AAA) | 主标题、核心指标数字、重要正文 |
| `--ink-secondary` | `#524B57` | 8.2:1 (AAA) | 次级正文、表格常规内容、表单标签 |
| `--ink-muted` | `#847C8A` | 4.2:1 | 辅助说明、占位提示、时间戳 |

### 2.3 品牌主色：玫瑰珊瑚红（Rose-Coral）
| Token | Hex | 用途 |
| --- | --- | --- |
| `--brand-50` | `#FFF1F4` | 选中菜单胶囊底色、图标微底、轻提示面 |
| `--brand-100` | `#FFE0E7` | 品牌徽章描边、进度条轨道 |
| `--brand-500` | `#E14B68` | 品牌 Logo 渐变、视觉锚点、滑块高亮 |
| `--brand-600` | `#C83553` | 主按钮背景、文字链接（白字对比度 > 5.4:1，符合 WCAG AA） |
| `--brand-700` | `#A52540` | 主按钮 Hover / Active 按压态 |
| `--accent-amber` | `#D97706` | 辅色暖琥珀（与玫瑰红组成温润的品牌氛围光） |

### 2.4 功能语义色（Harmonized Status Tokens）
| 语义 | 前景色 | 浅底色 | 描边色 | 典型场景 |
| --- | --- | --- | --- | --- |
| Success | `#0D8A67` | `#ECFDF5` | `#A7F3D0` | 邮箱通过、滑块验证通过、服务健康、多端在线 |
| Warning | `#B45309` | `#FFFBEB` | `#FDE68A` | 降级运行、管理员角色、中等风控提示 |
| Danger | `#BE123C` | `#FFF1F2` | `#FECDD3` | 域名邮箱拦截、禁用、踢下线、机器人拦截 |
| Info | `#475569` | `#F1F5F9` | `#E2E8F0` | 中性标签、系统来源、常规信息 |

---

## 3. 排版与字阶规范（Typography & Scale）

- **标题与展示字体**：`'SF Pro Display', 'PingFang SC', 'Hiragino Sans GB', 'Inter', -apple-system, sans-serif`（零阻塞外链字体，国内首屏 0ms 瞬开；负字距 `-0.02em` 提升精致感）。
- **正文与界面字体**：`'SF Pro Text', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif`。
- **数据 / 评分 / IP / 代码字体**：`'SF Mono', 'JetBrains Mono', ui-monospace, monospace` + `font-variant-numeric: tabular-nums`。

| 级别 | 字号 | 字重 | 行高 | 字距 | 场景 |
| --- | --- | --- | --- | --- | --- |
| Display | `28px` | `700` | `1.22` | `-0.025em` | 登录品牌展示大标题、KPI 核心数值 |
| Page Title | `22px` | `700` | `1.3` | `-0.02em` | 各业务页顶部主标题 |
| Section | `16px` | `600` | `1.4` | `-0.01em` | 卡片分区标题、弹窗标题 |
| Body | `14px` | `400/500` | `1.58` | `0` | 表格正文、表单输入、对话气泡 |
| Caption | `12px` | `400/500` | `1.45` | `0.01em` | 字段副标题、风控解释、辅助元信息 |

---

## 4. 圆角、阴影与动效规范（Geometry & Motion）

- **圆角体系**：`--radius-sm: 8px`（按钮/输入框）、`--radius-md: 12px`（内部面板/提示框）、`--radius-lg: 16px`（主卡片/弹窗）、`--radius-xl: 22px`（认证主容器）、`--radius-pill: 999px`（徽章与切换胶囊）。
- **轻盈弥散阴影**：
  - `--shadow-card`: `0 1px 2px rgba(26, 22, 29, 0.04), 0 8px 24px -12px rgba(26, 22, 29, 0.06)`
  - `--shadow-elevated`: `0 12px 36px -8px rgba(26, 22, 29, 0.12), 0 2px 8px rgba(26, 22, 29, 0.05)`
  - `--shadow-brand`: `0 8px 20px -6px rgba(200, 53, 83, 0.38)`
- **动效曲线**：`--ease-spring: cubic-bezier(0.22, 1, 0.36, 1)`，过渡时长 `160ms ~ 240ms`，尊重 `@media (prefers-reduced-motion: reduce)`。

---

## 5. 反模式清单与无障碍检查（Anti-Patterns & A11y Guardrails）

- **禁止**：默认高饱和紫蓝渐变、过重黑灰导航栏压迫感、无边框白卡片融进白底、同一页面出现超过 3 种高饱和色、阻塞渲染的海外 CDN 字体。
- **必须满足**：
  - 正文与按钮文字对比度 ≥ `4.5:1`（主标题 ≥ `12:1`）；
  - 所有输入框、按钮与交互控件具备清晰的 `:focus-visible` 玫瑰红外轮廓环；
  - 关键数值（评分、会话数、剩余时间）统一启用 `tabular-nums`；
  - 移动端 / 窄屏（`< 900px`）自动折叠登录分屏左侧面板，表格与表单保持舒适内边距。
