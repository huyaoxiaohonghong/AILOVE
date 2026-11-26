<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '@/plugins/element-plus'
import {
  ChatDotRound,
  Collection,
  Delete,
  Download,
  Files,
  FolderOpened,
  MagicStick,
  Plus,
  Reading,
  Refresh,
  Search,
  Upload,
} from '@element-plus/icons-vue'
import {
  compileKbWiki,
  createKbBase,
  deleteKbBase,
  deleteKbPage,
  deleteKbSource,
  exportKbSkillZip,
  fetchKbBases,
  fetchKbDetail,
  fetchKbPage,
  importKbBundle,
  lintKbWiki,
  publishKbSkill,
  testKbSkillQuery,
  updateKbBase,
  updateKbPage,
  updateKbSkill,
  uploadKbSources,
  type KBDetailResult,
  type KBLintReport,
  type KBTestCitationItem,
  type KBVisibility,
  type KBWikiBaseItem,
  type KBWikiPageItem,
} from '@/api/kb'
import { renderMarkdown } from '@/utils/markdown'

const router = useRouter()

const loadingList = ref(false)
const loadingDetail = ref(false)
const compiling = ref(false)
const linting = ref(false)
const publishingSkill = ref(false)
const testingQuery = ref(false)
const uploadingSources = ref(false)
const importingBundle = ref(false)

const kbList = ref<KBWikiBaseItem[]>([])
const searchKeyword = ref('')
const activeKbId = ref<number | null>(null)
const detail = ref<KBDetailResult | null>(null)
const activeTab = ref<'raw' | 'wiki' | 'skill' | 'lint' | 'cli'>('raw')

// raw/ 上传控制
const rawFileInputRef = ref<HTMLInputElement | null>(null)
const autoCompileOnUpload = ref(true)
const compileUseLlm = ref(true)

// wiki/ 浏览与编辑
type WikiInspectorMode = 'page' | 'schema' | 'index' | 'log'
const wikiMode = ref<WikiInspectorMode>('index')
const activePage = ref<KBWikiPageItem | null>(null)
const wikiEditing = ref(false)
const schemaEditing = ref('')
const pageEditForm = reactive({
  title: '',
  summary: '',
  content_md: '',
})

// SKILL.md 表单与检索测试
const skillForm = reactive({
  name: '',
  slug: '',
  description: '',
  triggersText: '',
  version: '1.0.0',
  visibility: 'private' as KBVisibility,
  is_enabled: true,
  skill_md: '',
})
const testQueryText = ref('')
const testCitations = ref<KBTestCitationItem[]>([])

// Lint
const lintReport = ref<KBLintReport | null>(null)

// 新建知识库弹窗
const createVisible = ref(false)
const createForm = reactive({
  name: '',
  slug: '',
  description: '',
  category: 'love_method',
  visibility: 'private' as KBVisibility,
})

// 整包导入（文件 + SKILL.md）弹窗
const importVisible = ref(false)
const importMode = ref<'zip' | 'folder'>('zip')
const bundleZipInputRef = ref<HTMLInputElement | null>(null)
const bundleFolderInputRef = ref<HTMLInputElement | null>(null)
const selectedZipFile = ref<File | null>(null)
const selectedFolderFiles = ref<File[]>([])
const importForm = reactive({
  name: '',
  visibility: 'private' as KBVisibility,
  autoCompile: true,
  useLlm: true,
})

const filteredKbList = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return kbList.value
  return kbList.value.filter(
    (item) =>
      item.name.toLowerCase().includes(kw) ||
      item.slug.toLowerCase().includes(kw) ||
      item.description.toLowerCase().includes(kw),
  )
})

const activeKb = computed(() => detail.value?.kb ?? null)
const canManage = computed(() => Boolean(detail.value?.can_manage))
const pendingCount = computed(
  () => (detail.value?.sources || []).filter((s) => s.ingest_status !== 'ingested').length,
)

const renderedWikiHtml = computed(() => {
  if (wikiMode.value === 'index') return renderMarkdown(activeKb.value?.index_md || '')
  if (wikiMode.value === 'log') return renderMarkdown(activeKb.value?.log_md || '')
  if (wikiMode.value === 'schema') return renderMarkdown(activeKb.value?.schema_md || '')
  return renderMarkdown(activePage.value?.content_md || '')
})

async function loadKbList(selectId?: number) {
  loadingList.value = true
  try {
    const res = await fetchKbBases()
    kbList.value = res.items
    const targetId = selectId || activeKbId.value || res.items[0]?.id || null
    if (targetId && res.items.some((item) => item.id === targetId)) {
      await selectKb(targetId)
    } else if (res.items.length > 0) {
      await selectKb(res.items[0].id)
    } else {
      activeKbId.value = null
      detail.value = null
    }
  } finally {
    loadingList.value = false
  }
}

async function selectKb(kbId: number) {
  activeKbId.value = kbId
  loadingDetail.value = true
  try {
    const res = await fetchKbDetail(kbId)
    detail.value = res
    schemaEditing.value = res.kb.schema_md || ''
    lintReport.value = res.kb.last_lint_report || null
    syncSkillForm(res)
    testCitations.value = []
    wikiEditing.value = false
    if (res.pages.length > 0) {
      const firstNonOverview = res.pages.find((p) => p.page_type !== 'overview') || res.pages[0]
      await openWikiPage(firstNonOverview.id)
    } else {
      wikiMode.value = 'index'
      activePage.value = null
    }
  } finally {
    loadingDetail.value = false
  }
}

function syncSkillForm(res: KBDetailResult) {
  const sk = res.skill
  if (sk) {
    skillForm.name = sk.name
    skillForm.slug = sk.slug
    skillForm.description = sk.description
    skillForm.triggersText = (sk.triggers || []).join(', ')
    skillForm.version = sk.version || '1.0.0'
    skillForm.visibility = sk.visibility
    skillForm.is_enabled = sk.is_enabled
    skillForm.skill_md = sk.skill_md || ''
  } else {
    skillForm.name = res.kb.name
    skillForm.slug = res.kb.slug
    skillForm.description = res.kb.description || `调用「${res.kb.name}」知识库回答相关问题`
    skillForm.triggersText = res.kb.name
    skillForm.version = '1.0.0'
    skillForm.visibility = res.kb.visibility
    skillForm.is_enabled = true
    skillForm.skill_md = ''
  }
}

async function openWikiPage(pageId: number) {
  if (!activeKbId.value) return
  wikiMode.value = 'page'
  wikiEditing.value = false
  const page = await fetchKbPage(activeKbId.value, pageId)
  activePage.value = page
  pageEditForm.title = page.title
  pageEditForm.summary = page.summary
  pageEditForm.content_md = page.content_md || ''
}

function jumpByWikilink(target: string) {
  const pages = detail.value?.pages || []
  const key = target.trim().toLowerCase()
  const matched = pages.find(
    (p) => p.title.trim().toLowerCase() === key || p.slug.trim().toLowerCase() === key,
  )
  if (matched) {
    void openWikiPage(matched.id)
  } else {
    ElMessage.info(`暂未找到词条「${target}」，可在编译或编辑后补充`)
  }
}

async function handleCreateKb() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  const kb = await createKbBase({
    name: createForm.name.trim(),
    slug: createForm.slug.trim() || undefined,
    description: createForm.description.trim(),
    category: createForm.category,
    visibility: createForm.visibility,
  })
  createVisible.value = false
  createForm.name = ''
  createForm.slug = ''
  createForm.description = ''
  ElMessage.success('知识库创建成功，可上传本地文件编译')
  await loadKbList(kb.id)
}

async function handleDeleteKb() {
  if (!activeKb.value) return
  try {
    await ElMessageBox.confirm(
      `确认删除知识库「${activeKb.value.name}」及其所有 raw/ 资料、Wiki 词条和 Skill？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    const deletedId = activeKb.value.id
    await deleteKbBase(deletedId)
    ElMessage.success('知识库已删除')
    activeKbId.value = null
    await loadKbList()
  } catch {
    // 取消
  }
}

function triggerRawFilePicker() {
  rawFileInputRef.value?.click()
}

async function onRawFilesSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || !activeKbId.value) return

  uploadingSources.value = true
  try {
    const res = await uploadKbSources(activeKbId.value, files, {
      relPaths: files.map((f) => f.webkitRelativePath || f.name),
      autoCompile: autoCompileOnUpload.value,
      useLlm: compileUseLlm.value,
    })
    ElMessage.success(
      `上传 ${res.uploaded} 份文件` +
        (res.deduplicated ? `（跳过重复 ${res.deduplicated} 份）` : '') +
        (autoCompileOnUpload.value ? '并已编译为 Wiki' : ''),
    )
    await loadKbList(activeKbId.value)
    if (autoCompileOnUpload.value) {
      activeTab.value = 'wiki'
    }
  } finally {
    uploadingSources.value = false
  }
}

async function handleDeleteSource(sourceId: number) {
  if (!activeKbId.value) return
  await deleteKbSource(activeKbId.value, sourceId)
  ElMessage.success('已移除源文件')
  await selectKb(activeKbId.value)
}

async function handleCompile(recompileAll = false) {
  if (!activeKbId.value) return
  compiling.value = true
  try {
    const res = await compileKbWiki(activeKbId.value, {
      use_llm: compileUseLlm.value,
      recompile_all: recompileAll,
    })
    ElMessage.success(
      `编译完成（${res.compile_mode === 'llm' ? 'LLM 深度编排' : '结构化入库'}）：${res.compiled_sources} 份文件 -> ${res.generated_pages} 篇词条`,
    )
    await loadKbList(activeKbId.value)
    activeTab.value = 'wiki'
  } finally {
    compiling.value = false
  }
}

async function handleSaveSchema() {
  if (!activeKbId.value) return
  await updateKbBase(activeKbId.value, { schema_md: schemaEditing.value })
  ElMessage.success('SCHEMA.md 已保存')
  await selectKb(activeKbId.value)
}

async function handleSavePage() {
  if (!activeKbId.value || !activePage.value) return
  const updated = await updateKbPage(activeKbId.value, activePage.value.id, {
    title: pageEditForm.title.trim(),
    summary: pageEditForm.summary.trim(),
    content_md: pageEditForm.content_md,
  })
  activePage.value = updated
  wikiEditing.value = false
  ElMessage.success('词条已保存并更新 index.md')
  await selectKb(activeKbId.value)
  await openWikiPage(updated.id)
}

async function handleDeletePage() {
  if (!activeKbId.value || !activePage.value) return
  await deleteKbPage(activeKbId.value, activePage.value.id)
  ElMessage.success('已删除词条')
  await selectKb(activeKbId.value)
}

async function handleRunLint() {
  if (!activeKbId.value) return
  linting.value = true
  try {
    const report = await lintKbWiki(activeKbId.value)
    lintReport.value = report
    ElMessage.success(`Wiki 健康体检完成：${report.score} / 100 分`)
    await loadKbList(activeKbId.value)
  } finally {
    linting.value = false
  }
}

async function handlePublishSkill(useAutoTemplate = false) {
  if (!activeKbId.value) return
  publishingSkill.value = true
  try {
    const triggers = skillForm.triggersText
      .split(/[,，\n]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    const saved = await publishKbSkill(activeKbId.value, {
      name: skillForm.name.trim() || activeKb.value?.name,
      slug: skillForm.slug.trim() || undefined,
      description: skillForm.description.trim(),
      triggers,
      skill_md: useAutoTemplate ? '' : skillForm.skill_md.trim(),
      version: skillForm.version.trim() || '1.0.0',
      visibility: skillForm.visibility,
      is_enabled: skillForm.is_enabled,
    })
    ElMessage.success(`Skill「${saved.name}」(/skill:${saved.slug}) 已发布并激活`)
    await loadKbList(activeKbId.value)
    activeTab.value = 'skill'
  } finally {
    publishingSkill.value = false
  }
}

async function handleToggleSkillEnabled(val: boolean) {
  if (!detail.value?.skill) return
  await updateKbSkill(detail.value.skill.id, { is_enabled: val })
  ElMessage.success(val ? '已开启该 Skill 调用' : '已暂停该 Skill 调用')
  await loadKbList(activeKbId.value || undefined)
}

async function handleTestSkillQuery() {
  if (!detail.value?.skill) {
    ElMessage.warning('请先点击「发布/激活 Skill」再测试检索')
    return
  }
  const q = testQueryText.value.trim()
  if (!q) {
    ElMessage.warning('请输入要测试检索的问题')
    return
  }
  testingQuery.value = true
  try {
    const res = await testKbSkillQuery(detail.value.skill.id, q, 4)
    testCitations.value = res.citations
    if (res.citations.length === 0) {
      ElMessage.info('暂未命中相关词条，建议先编译更多 raw/ 资料')
    }
  } finally {
    testingQuery.value = false
  }
}

async function handleExportZip() {
  if (!activeKb.value) return
  const slug = detail.value?.skill?.slug || activeKb.value.slug
  const fname = await exportKbSkillZip(activeKb.value.id, slug)
  ElMessage.success(`已导出完整 Skill 包：${fname}`)
}

function goPlaygroundWithSkill() {
  if (!detail.value?.skill) return
  void router.push({ path: '/ai-playground', query: { skill_id: String(detail.value.skill.id) } })
}

function onBundleZipChange(e: Event) {
  const input = e.target as HTMLInputElement
  selectedZipFile.value = input.files?.[0] || null
  input.value = ''
}

function onBundleFolderChange(e: Event) {
  const input = e.target as HTMLInputElement
  selectedFolderFiles.value = Array.from(input.files || [])
  input.value = ''
}

async function handleImportBundle() {
  if (importMode.value === 'zip' && !selectedZipFile.value) {
    ElMessage.warning('请先选择要上传的 .zip 整包压缩文件')
    return
  }
  if (importMode.value === 'folder' && selectedFolderFiles.value.length === 0) {
    ElMessage.warning('请先选择包含文档与 SKILL.md 的本地目录')
    return
  }
  importingBundle.value = true
  try {
    const res = await importKbBundle({
      bundleZip: importMode.value === 'zip' ? selectedZipFile.value : null,
      files: importMode.value === 'folder' ? selectedFolderFiles.value : undefined,
      relPaths:
        importMode.value === 'folder'
          ? selectedFolderFiles.value.map((f) => f.webkitRelativePath || f.name)
          : undefined,
      name: importForm.name.trim(),
      visibility: importForm.visibility,
      autoCompile: importForm.autoCompile,
      useLlm: importForm.useLlm,
    })
    ElMessage.success(
      `整包导入成功！Skill「${res.skill.name}」(${res.imported_raw} 份资料 / ${res.imported_wiki} 篇词条) 已可调用`,
    )
    importVisible.value = false
    selectedZipFile.value = null
    selectedFolderFiles.value = []
    importForm.name = ''
    await loadKbList(res.kb.id)
    activeTab.value = 'skill'
  } finally {
    importingBundle.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

onMounted(() => {
  void loadKbList()
})
</script>

<template>
  <div class="kb-studio-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">LLM Wiki 知识库 &amp; Skill 工坊</h2>
        <p class="page-subtitle">
          遵循 raw/ → wiki/ → index.md 三层互链架构：上传本地文件编译为知识库、封装为 SKILL.md 整包上传并在对话中实时调用
        </p>
      </div>
      <div class="header-actions">
        <el-button type="primary" plain :icon="Upload" @click="importVisible = true">
          整包上传 (文件 + SKILL.md)
        </el-button>
        <el-button type="primary" :icon="Plus" @click="createVisible = true">
          新建知识库
        </el-button>
      </div>
    </div>

    <div class="studio-grid">
      <!-- 左侧知识库列表 -->
      <aside class="kb-rail">
        <div class="rail-search">
          <el-input
            v-model="searchKeyword"
            placeholder="筛选知识库 / Skill..."
            clearable
            size="small"
            :prefix-icon="Search"
          />
        </div>

        <div v-loading="loadingList" class="rail-list">
          <el-empty v-if="filteredKbList.length === 0" description="暂无知识库，点击右上角新建或整包导入" />
          <div
            v-for="item in filteredKbList"
            :key="item.id"
            class="kb-card"
            :class="{ 'is-active': item.id === activeKbId }"
            @click="selectKb(item.id)"
          >
            <div class="kb-card-top">
              <span class="kb-card-name">{{ item.name }}</span>
              <el-tag
                size="small"
                :type="item.visibility === 'public' ? 'success' : 'info'"
                effect="plain"
              >
                {{ item.visibility === 'public' ? '公开' : '私有' }}
              </el-tag>
            </div>
            <div class="kb-card-slug">/skill:{{ item.skill?.slug || item.slug }}</div>
            <div class="kb-card-meta">
              <span>{{ item.source_count }} 源文件</span>
              <span>{{ item.page_count }} Wiki</span>
              <span v-if="item.skill?.is_enabled" class="skill-on">Skill 已激活</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右侧知识库详情工作区 -->
      <main v-loading="loadingDetail" class="kb-workspace">
        <el-empty
          v-if="!activeKb"
          description="选择左侧知识库，或点击右上角「整包上传 (文件 + SKILL.md)」快速开启"
        />

        <template v-else>
          <div class="ws-banner">
            <div class="ws-banner-info">
              <div class="ws-title-row">
                <el-icon><Collection /></el-icon>
                <span class="ws-name">{{ activeKb.name }}</span>
                <el-tag size="small" effect="plain">{{ activeKb.slug }}</el-tag>
                <el-tag
                  v-if="activeKb.last_lint_score !== null"
                  size="small"
                  :type="activeKb.last_lint_score >= 80 ? 'success' : 'warning'"
                >
                  健康度 {{ activeKb.last_lint_score }}分
                </el-tag>
              </div>
              <p class="ws-desc">{{ activeKb.description || '基于 LLM Wiki 架构增量编排的互链知识库' }}</p>
            </div>

            <div class="ws-banner-ops">
              <el-button size="small" :icon="Download" @click="handleExportZip">
                导出 Skill.zip
              </el-button>
              <el-button
                v-if="detail?.skill"
                size="small"
                type="primary"
                :icon="ChatDotRound"
                @click="goPlaygroundWithSkill"
              >
                去工作台调用
              </el-button>
              <el-button
                v-if="canManage"
                size="small"
                type="danger"
                plain
                :icon="Delete"
                @click="handleDeleteKb"
              />
            </div>
          </div>

          <el-tabs v-model="activeTab" class="ws-tabs">
            <!-- Tab 1: raw/ 原始资料 -->
            <el-tab-pane :label="`raw/ 原始资料 (${detail?.sources.length || 0})`" name="raw">
              <div class="tab-toolbar">
                <div class="toolbar-left">
                  <input
                    ref="rawFileInputRef"
                    type="file"
                    multiple
                    accept=".md,.markdown,.txt,.csv,.json,.html,.htm,.docx,.pdf"
                    class="hidden-file-input"
                    @change="onRawFilesSelected"
                  />
                  <el-button
                    v-if="canManage"
                    type="primary"
                    :loading="uploadingSources"
                    :icon="Upload"
                    @click="triggerRawFilePicker"
                  >
                    上传本地文件 (MD/TXT/PDF/DOCX/CSV)
                  </el-button>
                  <el-checkbox v-model="autoCompileOnUpload">上传后自动编译入库</el-checkbox>
                  <el-checkbox v-model="compileUseLlm">优先用 LLM 深度编排</el-checkbox>
                </div>
                <div class="toolbar-right">
                  <el-button
                    v-if="canManage"
                    type="success"
                    plain
                    :loading="compiling"
                    :disabled="pendingCount === 0"
                    :icon="MagicStick"
                    @click="handleCompile(false)"
                  >
                    编译待入库 ({{ pendingCount }})
                  </el-button>
                  <el-button
                    v-if="canManage"
                    plain
                    :loading="compiling"
                    :disabled="(detail?.sources.length || 0) === 0"
                    :icon="Refresh"
                    @click="handleCompile(true)"
                  >
                    全量重编
                  </el-button>
                </div>
              </div>

              <el-table :data="detail?.sources || []" stripe size="small" style="width: 100%">
                <el-table-column prop="rel_path" label="raw/ 相对路径" min-width="200" />
                <el-table-column prop="mime_type" label="格式" width="150" show-overflow-tooltip />
                <el-table-column label="大小 / 字符" width="140">
                  <template #default="{ row }">
                    {{ formatSize(row.file_size) }} · {{ row.char_count }} 字
                  </template>
                </el-table-column>
                <el-table-column label="LLM Wiki 状态" width="120">
                  <template #default="{ row }">
                    <el-tag
                      size="small"
                      :type="row.ingest_status === 'ingested' ? 'success' : row.ingest_status === 'failed' ? 'danger' : 'warning'"
                    >
                      {{ row.ingest_status === 'ingested' ? '已编译' : row.ingest_status === 'failed' ? '失败' : '待编译' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column v-if="canManage" label="操作" width="80" align="right">
                  <template #default="{ row }">
                    <el-button link type="danger" @click="handleDeleteSource(row.id)">移除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- Tab 2: wiki/ 互链浏览器 -->
            <el-tab-pane :label="`wiki/ 知识图谱 (${detail?.pages.length || 0})`" name="wiki">
              <div class="wiki-split">
                <div class="wiki-tree">
                  <div class="tree-group-label">系统索引层</div>
                  <div
                    class="tree-node"
                    :class="{ 'is-active': wikiMode === 'index' }"
                    @click="wikiMode = 'index'"
                  >
                    📑 index.md（全库地图）
                  </div>
                  <div
                    class="tree-node"
                    :class="{ 'is-active': wikiMode === 'schema' }"
                    @click="wikiMode = 'schema'"
                  >
                    📐 SCHEMA.md（编译规范）
                  </div>
                  <div
                    class="tree-node"
                    :class="{ 'is-active': wikiMode === 'log' }"
                    @click="wikiMode = 'log'"
                  >
                    📜 log.md（操作流水）
                  </div>

                  <div class="tree-group-label" style="margin-top: 12px">Wiki 词条页</div>
                  <div
                    v-for="p in detail?.pages || []"
                    :key="p.id"
                    class="tree-node"
                    :class="{ 'is-active': wikiMode === 'page' && activePage?.id === p.id }"
                    @click="openWikiPage(p.id)"
                  >
                    <span class="node-type">{{ p.page_type }}</span>
                    <span class="node-title">{{ p.title }}</span>
                  </div>
                </div>

                <div class="wiki-reader">
                  <template v-if="wikiMode === 'schema'">
                    <div class="reader-head">
                      <strong>SCHEMA.md（LLM Wiki 编排与引用规范）</strong>
                      <el-button v-if="canManage" type="primary" size="small" @click="handleSaveSchema">
                        保存 SCHEMA.md
                      </el-button>
                    </div>
                    <el-input
                      v-model="schemaEditing"
                      type="textarea"
                      :rows="16"
                      :readonly="!canManage"
                      class="mono-editor"
                    />
                  </template>

                  <template v-else-if="wikiMode === 'index' || wikiMode === 'log'">
                    <div class="reader-head">
                      <strong>{{ wikiMode === 'index' ? 'index.md · 知识全览地图' : 'log.md · 追加式时间线日志' }}</strong>
                    </div>
                    <div class="md-preview" v-html="renderedWikiHtml" />
                  </template>

                  <template v-else-if="activePage">
                    <div class="reader-head">
                      <div>
                        <strong>{{ activePage.title }}</strong>
                        <el-tag size="small" effect="plain" style="margin-left: 8px">
                          {{ activePage.page_path }} · v{{ activePage.version }}
                        </el-tag>
                      </div>
                      <div v-if="canManage" class="reader-ops">
                        <el-button size="small" @click="wikiEditing = !wikiEditing">
                          {{ wikiEditing ? '取消编辑' : '编辑词条' }}
                        </el-button>
                        <el-button v-if="wikiEditing" size="small" type="primary" @click="handleSavePage">
                          保存
                        </el-button>
                        <el-button size="small" type="danger" plain @click="handleDeletePage">
                          删除
                        </el-button>
                      </div>
                    </div>

                    <div v-if="activePage.links.length > 0" class="wikilink-bar">
                      <span class="wl-label">[[互链词条]]：</span>
                      <el-tag
                        v-for="lnk in activePage.links"
                        :key="lnk"
                        size="small"
                        class="wl-chip"
                        @click="jumpByWikilink(lnk)"
                      >
                        [[{{ lnk }}]]
                      </el-tag>
                    </div>

                    <template v-if="wikiEditing">
                      <el-input v-model="pageEditForm.title" placeholder="标题" style="margin-bottom: 8px" />
                      <el-input v-model="pageEditForm.summary" placeholder="一句话摘要" style="margin-bottom: 8px" />
                      <el-input
                        v-model="pageEditForm.content_md"
                        type="textarea"
                        :rows="14"
                        class="mono-editor"
                      />
                    </template>
                    <div v-else class="md-preview" v-html="renderedWikiHtml" />
                  </template>
                </div>
              </div>
            </el-tab-pane>

            <!-- Tab 3: SKILL.md 技能封装与测试 -->
            <el-tab-pane label="SKILL.md 技能工坊" name="skill">
              <div class="skill-layout">
                <div class="skill-form-card">
                  <div class="card-head">
                    <strong>将当前知识库封装为可调用 Skill</strong>
                    <el-switch
                      v-if="detail?.skill && canManage"
                      :model-value="detail.skill.is_enabled"
                      active-text="已启用调用"
                      inactive-text="已暂停"
                      @change="(val: boolean) => handleToggleSkillEnabled(val)"
                    />
                  </div>
                  <el-form label-width="96px" size="small">
                    <el-form-item label="Skill 名称">
                      <el-input v-model="skillForm.name" :disabled="!canManage" />
                    </el-form-item>
                    <el-form-item label="触发 Slug">
                      <el-input
                        v-model="skillForm.slug"
                        :disabled="!canManage || Boolean(detail?.skill)"
                        placeholder="支持 /skill:slug 直接呼出"
                      />
                    </el-form-item>
                    <el-form-item label="触发关键词">
                      <el-input
                        v-model="skillForm.triggersText"
                        :disabled="!canManage"
                        placeholder="逗号分隔，如：沟通技巧, 已读不回, 约会复盘"
                      />
                    </el-form-item>
                    <el-form-item label="场景描述">
                      <el-input v-model="skillForm.description" :disabled="!canManage" />
                    </el-form-item>
                    <el-form-item label="可见范围">
                      <el-select v-model="skillForm.visibility" :disabled="!canManage" style="width: 160px">
                        <el-option label="私有（仅自己可见调用）" value="private" />
                        <el-option label="公开（全平台与小程序可用）" value="public" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="SKILL.md">
                      <el-input
                        v-model="skillForm.skill_md"
                        type="textarea"
                        :rows="11"
                        :disabled="!canManage"
                        class="mono-editor"
                        placeholder="留空点击下方「生成并发布」将自动按 LLM Wiki 标准生成带 YAML Frontmatter 的 SKILL.md"
                      />
                    </el-form-item>
                  </el-form>
                  <div v-if="canManage" class="skill-btn-row">
                    <el-button
                      type="primary"
                      :loading="publishingSkill"
                      :icon="MagicStick"
                      @click="handlePublishSkill(false)"
                    >
                      保存并激活 Skill
                    </el-button>
                    <el-button
                      plain
                      :loading="publishingSkill"
                      @click="handlePublishSkill(true)"
                    >
                      按最新索引重建 SKILL.md
                    </el-button>
                  </div>
                </div>

                <!-- 在线检索测试 -->
                <div class="skill-test-card">
                  <div class="card-head">
                    <strong><el-icon><Reading /></el-icon> 在线测试 Skill 命中与引用效果</strong>
                    <el-tag v-if="detail?.skill" size="small" type="success" effect="plain">
                      已调用 {{ detail.skill.usage_count }} 次
                    </el-tag>
                  </div>
                  <div class="test-input-row">
                    <el-input
                      v-model="testQueryText"
                      placeholder="输入业务问题，验证能精准命中哪些 Wiki 词条..."
                      @keyup.enter="handleTestSkillQuery"
                    />
                    <el-button type="primary" :loading="testingQuery" @click="handleTestSkillQuery">
                      检索测试
                    </el-button>
                  </div>
                  <el-empty v-if="testCitations.length === 0" description="输入问题测试 LLM Wiki 检索排序与 1 跳互链扩展" />
                  <div v-else class="citation-list">
                    <div v-for="c in testCitations" :key="`${c.page_path}-${c.title}`" class="citation-card">
                      <div class="cite-top">
                        <strong>{{ c.title }}</strong>
                        <div>
                          <el-tag size="small" effect="plain">{{ c.via }}</el-tag>
                          <el-tag size="small" type="info" style="margin-left: 6px">相关性 {{ c.score }}</el-tag>
                        </div>
                      </div>
                      <div class="cite-path">{{ c.page_path }}</div>
                      <p class="cite-excerpt">{{ c.excerpt }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <!-- Tab 4: Lint 健康体检 -->
            <el-tab-pane label="Lint 健康体检" name="lint">
              <div class="tab-toolbar">
                <span>定期巡检死链、孤立词条与未编译源文件，保持知识图谱长期高质量。</span>
                <el-button v-if="canManage" type="primary" :loading="linting" @click="handleRunLint">
                  立即运行 Wiki Lint
                </el-button>
              </div>
              <el-empty v-if="!lintReport" description="尚未执行过体检，点击右上角立即巡检" />
              <div v-else class="lint-grid">
                <div class="lint-score-box">
                  <div class="score-val">{{ lintReport.score }}</div>
                  <div class="score-label">健康度 / 100</div>
                  <div class="score-time">最近检查：{{ lintReport.checked_at }}</div>
                </div>
                <el-descriptions :column="2" border class="lint-desc">
                  <el-descriptions-item label="Wiki 词条总数">{{ lintReport.total_pages }}</el-descriptions-item>
                  <el-descriptions-item label="raw/ 资料总数">{{ lintReport.total_sources }}</el-descriptions-item>
                  <el-descriptions-item label="孤立词条（0入链）">
                    {{ lintReport.orphan_pages.length ? lintReport.orphan_pages.join('、') : '无 ✅' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="断链 [[wikilinks]]">
                    {{ lintReport.dangling_links.length ? lintReport.dangling_links.map(d => `${d.from}→[[${d.missing_target}]]`).join('；') : '无 ✅' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="待编译源文件">
                    {{ lintReport.pending_sources.length ? lintReport.pending_sources.join('、') : '已全部入库 ✅' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="过短/缺摘要页">
                    {{ [...lintReport.short_pages, ...lintReport.no_summary_pages].length || '无 ✅' }}
                  </el-descriptions-item>
                </el-descriptions>
              </div>
            </el-tab-pane>

            <!-- Tab 5: 本地整包 CLI 指南 -->
            <el-tab-pane label="本地整包 CLI 说明" name="cli">
              <el-alert
                type="info"
                show-icon
                :closable="false"
                title="如何用本地文件 + SKILL.md 整包上传到云平台？"
                description="方式 A：直接点击本页右上角「整包上传 (文件 + SKILL.md)」，选中本地目录或 .zip 即可自动建库并激活。方式 B：使用仓库自带 scripts/llm_wiki_skill_cli.py 脚本在终端一键打包并推送到云端。"
                style="margin-bottom: 14px"
              />
              <pre class="cli-code"># 1. 将本地文档目录打包为标准 LLM Wiki + SKILL.md 压缩包
python3 scripts/llm_wiki_skill_cli.py build ./my_docs \
  --name "专属知识库" \
  --triggers "关键词1,关键词2" \
  --out ./my-skill.zip

# 2. 将整包直接上传到云平台并自动激活可调用 Skill
python3 scripts/llm_wiki_skill_cli.py upload ./my-skill.zip \
  --server https://你的域名或服务地址 \
  --token "你的JWT_Token"</pre>
            </el-tab-pane>
          </el-tabs>
        </template>
      </main>
    </div>

    <!-- 新建知识库弹窗 -->
    <el-dialog v-model="createVisible" title="新建 LLM Wiki 知识库" width="480px">
      <el-form label-width="92px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="例如：高情商恋爱实战手册" />
        </el-form-item>
        <el-form-item label="Slug">
          <el-input v-model="createForm.slug" placeholder="留空自动生成（如 love-manual）" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="说明知识库包含哪些主题..." />
        </el-form-item>
        <el-form-item label="可见范围">
          <el-select v-model="createForm.visibility" style="width: 100%">
            <el-option label="私有（仅自己账号与小程序可见）" value="private" />
            <el-option label="公开（全站与小程序用户均可调用）" value="public" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateKb">确认创建</el-button>
      </template>
    </el-dialog>

    <!-- 整包上传 (文件 + SKILL.md) 弹窗 -->
    <el-dialog v-model="importVisible" title="整包上传（本地文件 + SKILL.md）" width="540px">
      <el-alert
        type="success"
        :closable="false"
        show-icon
        title="支持整个本地文件夹或 .zip 压缩包一次上传"
        description="包内包含 SKILL.md（及可选 wiki/、raw/、SCHEMA.md、index.md、log.md），云端将自动解析目录、编译缺失词条并立刻激活为可调用 Skill。"
        style="margin-bottom: 14px"
      />
      <el-tabs v-model="importMode" type="border-card" style="margin-bottom: 14px">
        <el-tab-pane label="上传 .zip 整包" name="zip">
          <input
            ref="bundleZipInputRef"
            type="file"
            accept=".zip"
            class="hidden-file-input"
            @change="onBundleZipChange"
          />
          <div class="bundle-drop">
            <el-button type="primary" plain :icon="Files" @click="bundleZipInputRef?.click()">
              选择 .zip 压缩包
            </el-button>
            <span class="bundle-picked">
              {{ selectedZipFile ? `已选：${selectedZipFile.name} (${formatSize(selectedZipFile.size)})` : '未选择文件（最大 20 MB）' }}
            </span>
          </div>
        </el-tab-pane>
        <el-tab-pane label="上传整个本地目录" name="folder">
          <input
            ref="bundleFolderInputRef"
            type="file"
            webkitdirectory
            multiple
            class="hidden-file-input"
            @change="onBundleFolderChange"
          />
          <div class="bundle-drop">
            <el-button type="primary" plain :icon="FolderOpened" @click="bundleFolderInputRef?.click()">
              选择本地知识库文件夹
            </el-button>
            <span class="bundle-picked">
              {{ selectedFolderFiles.length ? `已选目录内共 ${selectedFolderFiles.length} 个文件` : '将自动识别 SKILL.md、wiki/ 与 raw/ 文件' }}
            </span>
          </div>
        </el-tab-pane>
      </el-tabs>

      <el-form label-width="110px" size="small">
        <el-form-item label="自定义名称">
          <el-input v-model="importForm.name" placeholder="留空自动读取 SKILL.md 中的 name" />
        </el-form-item>
        <el-form-item label="可见性">
          <el-select v-model="importForm.visibility" style="width: 100%">
            <el-option label="私有（仅自己可调用）" value="private" />
            <el-option label="公开（团队与小程序可调用）" value="public" />
          </el-select>
        </el-form-item>
        <el-form-item label="未编译文档处理">
          <el-checkbox v-model="importForm.autoCompile">若无 wiki/ 则自动执行编译入库</el-checkbox>
          <el-checkbox v-model="importForm.useLlm">优先用 LLM 深度编排</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importingBundle" @click="handleImportBundle">
          上传整包并激活 Skill
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-studio-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
}

.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.studio-grid {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  min-height: 620px;
}

.kb-rail {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rail-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  max-height: 640px;
}

.kb-card {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #eef0f4;
  cursor: pointer;
  transition: all 0.16s ease;
}

.kb-card:hover {
  border-color: #f48fb1;
  background: #fff9fb;
}

.kb-card.is-active {
  border-color: #e1467b;
  background: #fff4f8;
}

.kb-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.kb-card-name {
  font-weight: 600;
  font-size: 13.5px;
  color: #1f2937;
}

.kb-card-slug {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 3px;
}

.kb-card-meta {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  font-size: 11.5px;
  color: #6b7280;
}

.skill-on {
  color: #16a34a;
  font-weight: 600;
}

.kb-workspace {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  min-width: 0;
}

.ws-banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 8px;
}

.ws-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ws-name {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}

.ws-desc {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: #6b7280;
}

.ws-banner-ops {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hidden-file-input {
  display: none;
}

.wiki-split {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 14px;
  min-height: 460px;
}

.wiki-tree {
  border-right: 1px solid #f1f5f9;
  padding-right: 10px;
  max-height: 520px;
  overflow-y: auto;
}

.tree-group-label {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  margin-bottom: 6px;
  text-transform: uppercase;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 12.5px;
  color: #374151;
  cursor: pointer;
}

.tree-node:hover {
  background: #f9fafb;
}

.tree-node.is-active {
  background: #fff1f5;
  color: #c83553;
  font-weight: 600;
}

.node-type {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: #f3f4f6;
  color: #6b7280;
}

.node-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wiki-reader {
  min-width: 0;
}

.reader-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.reader-ops {
  display: flex;
  gap: 8px;
}

.wikilink-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff9fb;
  border: 1px dashed #f3c4d3;
}

.wl-label {
  font-size: 12px;
  color: #9d174d;
  font-weight: 600;
}

.wl-chip {
  cursor: pointer;
}

.md-preview {
  padding: 12px 14px;
  border-radius: 10px;
  background: #fafafa;
  border: 1px solid #f1f5f9;
  max-height: 440px;
  overflow-y: auto;
  font-size: 13.5px;
  line-height: 1.7;
}

.mono-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
}

.skill-layout {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 16px;
}

.skill-form-card,
.skill-test-card {
  padding: 14px;
  border-radius: 10px;
  border: 1px solid #eef0f4;
  background: #fcfcfd;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.skill-btn-row {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.test-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 420px;
  overflow-y: auto;
}

.citation-card {
  padding: 10px 12px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
}

.cite-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cite-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.cite-excerpt {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: #4b5563;
  line-height: 1.5;
}

.lint-grid {
  display: grid;
  grid-template-columns: 190px 1fr;
  gap: 16px;
  align-items: start;
}

.lint-score-box {
  padding: 20px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #fff1f5, #fffafc);
  border: 1px solid #f7c5d5;
  text-align: center;
}

.score-val {
  font-size: 38px;
  font-weight: 800;
  color: #c83553;
}

.score-label {
  font-size: 12.5px;
  font-weight: 600;
  color: #8f234c;
}

.score-time {
  margin-top: 8px;
  font-size: 11px;
  color: #9e5872;
}

.cli-code {
  margin: 0;
  padding: 14px;
  border-radius: 10px;
  background: #111827;
  color: #e5e7eb;
  font-size: 12.5px;
  line-height: 1.6;
  overflow-x: auto;
}

.bundle-drop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 4px;
}

.bundle-picked {
  font-size: 12.5px;
  color: #4b5563;
}
</style>
