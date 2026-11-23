/**
 * 轻量级零依赖 XSS 安全 Markdown 渲染器
 * 先执行严格 HTML 转义，再解析代码块、表格、标题、列表、引用与安全行内样式。
 */

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function encodeUtf8Base64(text: string): string {
  try {
    const bytes = new TextEncoder().encode(text)
    let bin = ''
    for (const b of bytes) {
      bin += String.fromCharCode(b)
    }
    return btoa(bin)
  } catch {
    return ''
  }
}

export function decodeUtf8Base64(b64: string): string {
  try {
    const bin = atob(b64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i)
    }
    return new TextDecoder('utf-8').decode(bytes)
  } catch {
    return ''
  }
}

function renderInline(escaped: string): string {
  const codeSpans: string[] = []
  let out = escaped.replace(/`([^`\n]+)`/g, (_m, inner: string) => {
    const idx = codeSpans.length
    codeSpans.push(`<code class="md-inline-code">${inner}</code>`)
    return `\u0000ICODE_${idx}\u0000`
  })

  // 安全链接 [label](https://...)
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_m, label: string, url: string) =>
      `<a class="md-link" href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`,
  )

  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/~~([^~]+)~~/g, '<del>$1</del>')
  out = out.replace(/(^|[^\w*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')

  out = out.replace(/\u0000ICODE_(\d+)\u0000/g, (_m, i: string) => codeSpans[Number(i)] ?? '')
  return out
}

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim())
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return false
  return /^\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{0,}:?\s*\|?$/.test(trimmed)
}

function renderTextSegment(segment: string): string {
  const lines = segment.split('\n')
  const html: string[] = []
  let i = 0

  while (i < lines.length) {
    const rawLine = lines[i] ?? ''
    const trimmed = rawLine.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    // 标题 h1-h4
    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (headingMatch) {
      const level = headingMatch[1]?.length ?? 3
      const tag = `h${level}`
      html.push(
        `<${tag} class="md-h md-h${level}">${renderInline(escapeHtml(headingMatch[2] ?? ''))}</${tag}>`,
      )
      i += 1
      continue
    }

    // 分割线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      html.push('<hr class="md-hr" />')
      i += 1
      continue
    }

    // 引用块
    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = []
      while (i < lines.length && /^>\s?/.test((lines[i] ?? '').trim())) {
        quoteLines.push(
          renderInline(escapeHtml((lines[i] ?? '').trim().replace(/^>\s?/, ''))),
        )
        i += 1
      }
      html.push(`<blockquote class="md-quote">${quoteLines.join('<br />')}</blockquote>`)
      continue
    }

    // GFM 表格
    if (
      trimmed.includes('|') &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1] ?? '')
    ) {
      const headers = splitTableRow(rawLine)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && (lines[i] ?? '').includes('|') && (lines[i] ?? '').trim() !== '') {
        rows.push(splitTableRow(lines[i] ?? ''))
        i += 1
      }
      const thead = `<thead><tr>${headers
        .map((h) => `<th>${renderInline(escapeHtml(h))}</th>`)
        .join('')}</tr></thead>`
      const tbody = `<tbody>${rows
        .map(
          (r) =>
            `<tr>${headers
              .map((_, cIdx) => `<td>${renderInline(escapeHtml(r[cIdx] ?? ''))}</td>`)
              .join('')}</tr>`,
        )
        .join('')}</tbody>`
      html.push(`<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`)
      continue
    }

    // 无序列表
    if (/^[-*+]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^[-*+]\s+/.test((lines[i] ?? '').trim())) {
        const txt = (lines[i] ?? '').trim().replace(/^[-*+]\s+/, '')
        items.push(`<li>${renderInline(escapeHtml(txt))}</li>`)
        i += 1
      }
      html.push(`<ul class="md-list">${items.join('')}</ul>`)
      continue
    }

    // 有序列表
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test((lines[i] ?? '').trim())) {
        const txt = (lines[i] ?? '').trim().replace(/^\d+\.\s+/, '')
        items.push(`<li>${renderInline(escapeHtml(txt))}</li>`)
        i += 1
      }
      html.push(`<ol class="md-list">${items.join('')}</ol>`)
      continue
    }

    // 段落聚合（遇到空行或块级语法结束）
    const paraLines: string[] = []
    while (i < lines.length) {
      const cur = lines[i] ?? ''
      const curTrim = cur.trim()
      if (
        !curTrim ||
        /^(#{1,4})\s+/.test(curTrim) ||
        /^>\s?/.test(curTrim) ||
        /^[-*+]\s+/.test(curTrim) ||
        /^\d+\.\s+/.test(curTrim) ||
        /^(-{3,}|\*{3,}|_{3,})$/.test(curTrim) ||
        (curTrim.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1] ?? ''))
      ) {
        break
      }
      paraLines.push(renderInline(escapeHtml(cur)))
      i += 1
    }
    if (paraLines.length > 0) {
      html.push(`<p class="md-p">${paraLines.join('<br />')}</p>`)
    }
  }

  return html.join('')
}

export function renderMarkdown(source: string): string {
  const normalized = (source || '').replace(/\r\n?/g, '\n')
  if (!normalized.trim()) return ''

  const parts: string[] = []
  const fenceRegex = /```([A-Za-z0-9_+-]*)\n([\s\S]*?)```/g
  let lastIdx = 0
  let match: RegExpExecArray | null = fenceRegex.exec(normalized)

  while (match !== null) {
    if (match.index > lastIdx) {
      parts.push(renderTextSegment(normalized.slice(lastIdx, match.index)))
    }
    const lang = escapeHtml((match[1] || 'text').trim())
    const rawCode = (match[2] || '').replace(/\n$/, '')
    const b64 = encodeUtf8Base64(rawCode)
    parts.push(
      `<div class="md-code-block">` +
        `<div class="md-code-head">` +
        `<span class="md-code-lang">${lang}</span>` +
        `<button type="button" class="md-copy-btn" data-copy-b64="${b64}">复制代码</button>` +
        `</div>` +
        `<pre class="md-pre"><code>${escapeHtml(rawCode)}</code></pre>` +
        `</div>`,
    )
    lastIdx = fenceRegex.lastIndex
    match = fenceRegex.exec(normalized)
  }

  if (lastIdx < normalized.length) {
    // 处理流式输出尚未闭合的代码块
    const tail = normalized.slice(lastIdx)
    const openFence = /```([A-Za-z0-9_+-]*)\n([\s\S]*)$/.exec(tail)
    if (openFence) {
      const before = tail.slice(0, openFence.index)
      if (before) parts.push(renderTextSegment(before))
      const lang = escapeHtml((openFence[1] || 'text').trim())
      const rawCode = openFence[2] || ''
      const b64 = encodeUtf8Base64(rawCode)
      parts.push(
        `<div class="md-code-block">` +
          `<div class="md-code-head">` +
          `<span class="md-code-lang">${lang}</span>` +
          `<button type="button" class="md-copy-btn" data-copy-b64="${b64}">复制代码</button>` +
          `</div>` +
          `<pre class="md-pre"><code>${escapeHtml(rawCode)}</code></pre>` +
          `</div>`,
      )
    } else {
      parts.push(renderTextSegment(tail))
    }
  }

  return parts.join('')
}
