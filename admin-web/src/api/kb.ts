import { downloadAuthenticatedCsv } from '@/utils/download'
import { request } from '@/utils/request'

export type KBVisibility = 'private' | 'public'
export type KBPageType = 'summary' | 'concept' | 'entity' | 'insight' | 'overview'

export interface KBLintDanglingLink {
  from: string
  missing_target: string
}

export interface KBLintReport {
  score: number
  total_pages: number
  total_sources: number
  orphan_pages: string[]
  dangling_links: KBLintDanglingLink[]
  pending_sources: string[]
  short_pages: string[]
  no_summary_pages: string[]
  checked_at: string
}

export interface KBSkillItem {
  id: number
  kb_id: number
  kb_name?: string
  slug: string
  name: string
  description: string
  triggers: string[]
  skill_md: string
  version: string
  owner_scope: string
  visibility: KBVisibility
  is_enabled: boolean
  usage_count: number
  page_count?: number
  source_count?: number
  is_owner?: boolean
  updated_at: string | null
}

export interface KBWikiBaseItem {
  id: number
  slug: string
  name: string
  description: string
  category: string
  owner_scope: string
  visibility: KBVisibility
  schema_md: string
  index_md: string
  log_md: string
  source_count: number
  page_count: number
  last_lint_score: number | null
  last_lint_report: KBLintReport | null
  last_compiled_at: string | null
  created_at: string | null
  updated_at: string | null
  is_owner?: boolean
  skill?: KBSkillItem | null
}

export interface KBRawSourceItem {
  id: number
  kb_id: number
  filename: string
  rel_path: string
  mime_type: string
  file_size: number
  content_sha256: string
  char_count: number
  ingest_status: 'pending' | 'ingested' | 'failed'
  ingest_error: string
  ingested_at: string | null
  created_at: string | null
}

export interface KBWikiPageItem {
  id: number
  kb_id: number
  page_path: string
  slug: string
  title: string
  page_type: KBPageType
  summary: string
  content_md?: string
  links: string[]
  source_ids: number[]
  version: number
  updated_at: string | null
}

export interface KBDetailResult {
  kb: KBWikiBaseItem
  can_manage: boolean
  sources: KBRawSourceItem[]
  pages: KBWikiPageItem[]
  skill: KBSkillItem | null
}

export interface KBTestCitationItem {
  page_id: number
  page_path: string
  title: string
  page_type: string
  summary: string
  score: number
  via: string
  content_md: string
  excerpt: string
}

export function fetchKbBases() {
  return request<{ items: KBWikiBaseItem[] }>({
    url: '/kb/bases',
    method: 'get',
  })
}

export function createKbBase(data: {
  name: string
  slug?: string
  description?: string
  category?: string
  visibility?: KBVisibility
  schema_md?: string
}) {
  return request<KBWikiBaseItem>({
    url: '/kb/bases',
    method: 'post',
    data,
  })
}

export function fetchKbDetail(kbId: number) {
  return request<KBDetailResult>({
    url: `/kb/bases/${kbId}`,
    method: 'get',
  })
}

export function updateKbBase(
  kbId: number,
  data: Partial<{
    name: string
    description: string
    category: string
    visibility: KBVisibility
    schema_md: string
  }>,
) {
  return request<KBWikiBaseItem>({
    url: `/kb/bases/${kbId}`,
    method: 'patch',
    data,
  })
}

export function deleteKbBase(kbId: number) {
  return request<{ deleted_id: number }>({
    url: `/kb/bases/${kbId}`,
    method: 'delete',
  })
}

export function uploadKbSources(
  kbId: number,
  files: File[],
  options?: { relPaths?: string[]; autoCompile?: boolean; useLlm?: boolean },
) {
  const form = new FormData()
  for (const f of files) {
    form.append('files', f, f.name)
  }
  form.append('rel_paths_json', JSON.stringify(options?.relPaths || files.map((f) => f.name)))
  form.append('auto_compile', String(Boolean(options?.autoCompile)))
  form.append('use_llm', String(options?.useLlm ?? true))
  return request<{
    uploaded: number
    deduplicated: number
    sources: KBRawSourceItem[]
    compile_result: unknown
  }>({
    url: `/kb/bases/${kbId}/sources`,
    method: 'post',
    data: form,
    timeout: 120000,
  })
}

export function deleteKbSource(kbId: number, sourceId: number) {
  return request<{ deleted_id: number }>({
    url: `/kb/bases/${kbId}/sources/${sourceId}`,
    method: 'delete',
  })
}

export function compileKbWiki(
  kbId: number,
  data?: { source_ids?: number[]; use_llm?: boolean; config_id?: number; recompile_all?: boolean },
) {
  return request<{
    compiled_sources: number
    generated_pages: number
    compile_mode: string
    kb: KBWikiBaseItem
  }>({
    url: `/kb/bases/${kbId}/compile`,
    method: 'post',
    data: data || {},
    timeout: 180000,
  })
}

export function fetchKbPage(kbId: number, pageId: number) {
  return request<KBWikiPageItem>({
    url: `/kb/bases/${kbId}/pages/${pageId}`,
    method: 'get',
  })
}

export function updateKbPage(
  kbId: number,
  pageId: number,
  data: { title?: string; page_type?: KBPageType; summary?: string; content_md?: string },
) {
  return request<KBWikiPageItem>({
    url: `/kb/bases/${kbId}/pages/${pageId}`,
    method: 'put',
    data,
  })
}

export function deleteKbPage(kbId: number, pageId: number) {
  return request<{ deleted_id: number }>({
    url: `/kb/bases/${kbId}/pages/${pageId}`,
    method: 'delete',
  })
}

export function lintKbWiki(kbId: number) {
  return request<KBLintReport>({
    url: `/kb/bases/${kbId}/lint`,
    method: 'post',
  })
}

export function fileKbInsight(
  kbId: number,
  data: { title: string; content: string; source_question?: string },
) {
  return request<{ page: KBWikiPageItem; kb: KBWikiBaseItem }>({
    url: `/kb/bases/${kbId}/insights`,
    method: 'post',
    data,
  })
}

export function publishKbSkill(
  kbId: number,
  data?: Partial<{
    name: string
    slug: string
    description: string
    triggers: string[]
    skill_md: string
    version: string
    visibility: KBVisibility
    is_enabled: boolean
  }>,
) {
  return request<KBSkillItem>({
    url: `/kb/bases/${kbId}/skill/publish`,
    method: 'post',
    data: data || {},
  })
}

export function updateKbSkill(
  skillId: number,
  data: Partial<{
    name: string
    description: string
    triggers: string[]
    skill_md: string
    version: string
    visibility: KBVisibility
    is_enabled: boolean
  }>,
) {
  return request<KBSkillItem>({
    url: `/kb/skills/${skillId}`,
    method: 'patch',
    data,
  })
}

export function exportKbSkillZip(kbId: number, slug = 'knowledge') {
  return downloadAuthenticatedCsv(`/kb/bases/${kbId}/export-skill`, undefined, `${slug}-skill.zip`)
}

export function importKbBundle(data: {
  bundleZip?: File | null
  files?: File[]
  relPaths?: string[]
  name?: string
  visibility?: KBVisibility
  autoCompile?: boolean
  useLlm?: boolean
}) {
  const form = new FormData()
  if (data.bundleZip) {
    form.append('bundle_zip', data.bundleZip, data.bundleZip.name)
  } else if (data.files?.length) {
    for (const f of data.files) {
      form.append('files', f, f.name)
    }
    form.append('rel_paths_json', JSON.stringify(data.relPaths || data.files.map((f) => f.name)))
  }
  form.append('name', data.name || '')
  form.append('visibility', data.visibility || 'private')
  form.append('auto_compile', String(data.autoCompile ?? true))
  form.append('use_llm', String(data.useLlm ?? true))
  return request<{
    kb: KBWikiBaseItem
    skill: KBSkillItem
    imported_raw: number
    imported_wiki: number
    compile_result: unknown
  }>({
    url: '/kb/import-bundle',
    method: 'post',
    data: form,
    timeout: 180000,
  })
}

export function fetchCallableSkills() {
  return request<{ items: KBSkillItem[] }>({
    url: '/kb/skills',
    method: 'get',
  })
}

export function testKbSkillQuery(skillId: number, query: string, topK = 4) {
  return request<{
    skill: KBSkillItem
    kb_name: string
    query: string
    citations: KBTestCitationItem[]
  }>({
    url: `/kb/skills/${skillId}/test-query`,
    method: 'post',
    data: { query, top_k: topK },
  })
}
