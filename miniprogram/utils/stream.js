const env = require('../config/env')
const { getToken, clearAuthState, trySilentRelogin } = require('./request')

/**
 * 增量 UTF-8 解码器：纯 JS 实现，不依赖 TextDecoder，安全处理跨 chunk 截断的中文多字节序列。
 */
function createUtf8StreamDecoder() {
  let pending = []

  return function decode(arrayBuffer) {
    if (!arrayBuffer) return ''
    const incoming = new Uint8Array(arrayBuffer)
    let bytes
    if (pending.length > 0) {
      bytes = new Uint8Array(pending.length + incoming.length)
      bytes.set(pending, 0)
      bytes.set(incoming, pending.length)
      pending = []
    } else {
      bytes = incoming
    }

    let out = ''
    let i = 0
    const len = bytes.length

    while (i < len) {
      const b0 = bytes[i]
      if (b0 < 0x80) {
        out += String.fromCharCode(b0)
        i += 1
      } else if ((b0 & 0xe0) === 0xc0) {
        if (i + 1 >= len) {
          pending = Array.prototype.slice.call(bytes, i)
          break
        }
        const cp = ((b0 & 0x1f) << 6) | (bytes[i + 1] & 0x3f)
        out += String.fromCharCode(cp)
        i += 2
      } else if ((b0 & 0xf0) === 0xe0) {
        if (i + 2 >= len) {
          pending = Array.prototype.slice.call(bytes, i)
          break
        }
        const cp =
          ((b0 & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f)
        out += String.fromCharCode(cp)
        i += 3
      } else if ((b0 & 0xf8) === 0xf0) {
        if (i + 3 >= len) {
          pending = Array.prototype.slice.call(bytes, i)
          break
        }
        const cp =
          ((b0 & 0x07) << 18) |
          ((bytes[i + 1] & 0x3f) << 12) |
          ((bytes[i + 2] & 0x3f) << 6) |
          (bytes[i + 3] & 0x3f)
        const offset = cp - 0x10000
        out += String.fromCharCode(0xd800 + (offset >> 10), 0xdc00 + (offset & 0x3ff))
        i += 4
      } else {
        i += 1
      }
    }
    return out
  }
}

/**
 * 微信原生分块 SSE 流式请求封装（支持 meta / reasoning / delta / fallback / usage / done / error）
 */
function streamSseRequest(options) {
  const {
    url,
    data = {},
    timeout = 90000,
    onMeta,
    onReasoning,
    onDelta,
    onFallback,
    onUsage,
    onDone,
    onError,
  } = options

  const baseUrl = env.getEnvConfig().API_BASE_URL
  let sseBuffer = ''
  let receivedAnyEvent = false
  let aborted = false
  let finished = false
  let requestTask = null

  function normalizeLineEndings(text) {
    return text ? text.replace(/\r\n/g, '\n') : ''
  }

  function dispatchBlock(block) {
    const lines = block.split('\n')
    let dataLine = ''
    for (let i = 0; i < lines.length; i += 1) {
      if (lines[i].indexOf('data: ') === 0) {
        dataLine = lines[i].slice(6)
        break
      }
    }
    if (!dataLine) return
    let payload
    try {
      payload = JSON.parse(dataLine)
    } catch (_e) {
      return
    }
    receivedAnyEvent = true
    const evt = payload.event
    if (evt === 'meta' && payload.session_id) {
      if (onMeta) onMeta(payload)
    } else if (evt === 'fallback' && payload.content) {
      if (onFallback) onFallback(payload.content)
    } else if (evt === 'reasoning' && payload.content) {
      if (onReasoning) onReasoning(payload.content)
    } else if (evt === 'delta' && payload.content) {
      if (onDelta) onDelta(payload.content)
    } else if (evt === 'usage' && payload.content) {
      if (onUsage) onUsage(Number(payload.content) || 0)
    } else if (evt === 'done') {
      if (onDone) onDone(payload.session_id || '')
    } else if (evt === 'error') {
      if (onError) onError(payload.message || '流式生成发生错误')
    }
  }

  const promise = new Promise((resolve, reject) => {
    function startAttempt(retried) {
      const currentToken = getToken()
      const decodeChunk = createUtf8StreamDecoder()
      sseBuffer = ''

      requestTask = wx.request({
        url: `${baseUrl}${url}`,
        method: 'POST',
        data,
        timeout,
        enableChunked: true,
        responseType: 'arraybuffer',
        header: Object.assign(
          { 'Content-Type': 'application/json' },
          currentToken ? { Authorization: `Bearer ${currentToken}` } : {}
        ),
        success(res) {
          if (finished) return
          const statusCode = res.statusCode

          if (statusCode === 401) {
            clearAuthState()
            if (Boolean(currentToken) && !retried && !aborted && !receivedAnyEvent) {
              trySilentRelogin().then((ok) => {
                if (ok && !aborted && !finished) {
                  startAttempt(true)
                } else if (!finished) {
                  finished = true
                  reject(new Error('登录已过期，请重新登录'))
                }
              })
              return
            }
            finished = true
            reject(new Error('登录已过期，请重新登录'))
            return
          }

          finished = true

          if (statusCode >= 400) {
            let errMsg = `请求失败 (HTTP ${statusCode})`
            try {
              let rawText = ''
              if (res.data instanceof ArrayBuffer) {
                rawText = decodeChunk(res.data)
              } else if (typeof res.data === 'string') {
                rawText = res.data
              } else if (res.data && typeof res.data === 'object') {
                rawText = JSON.stringify(res.data)
              }
              // 微信开启 enableChunked 时，4xx/5xx 响应体常先流向 onChunkReceived，res.data 为空
              if (!rawText.trim() && sseBuffer.trim()) {
                rawText = sseBuffer
              }
              const parsed = JSON.parse(rawText)
              if (parsed && (parsed.message || parsed.detail)) {
                errMsg = String(parsed.message || parsed.detail)
              }
            } catch (_e) {
              // 忽略非 JSON 错误体解析异常
            }
            reject(new Error(errMsg))
            return
          }

          if (!receivedAnyEvent && res.data) {
            const fullText =
              res.data instanceof ArrayBuffer
                ? decodeChunk(res.data)
                : typeof res.data === 'string'
                  ? res.data
                  : ''
            sseBuffer += normalizeLineEndings(fullText)
          }

          if (sseBuffer.trim()) {
            const rest = sseBuffer.split('\n\n')
            sseBuffer = ''
            rest.forEach((b) => {
              if (b.trim()) dispatchBlock(b)
            })
          }
          resolve()
        },
        fail(err) {
          if (finished) return
          finished = true
          if (aborted) {
            resolve()
            return
          }
          reject(new Error((err && err.errMsg) || '流式连接中断，请稍后重试'))
        },
      })

      if (requestTask && typeof requestTask.onChunkReceived === 'function') {
        requestTask.onChunkReceived((res) => {
          if (aborted || !res || !res.data) return
          const piece = normalizeLineEndings(decodeChunk(res.data))
          if (!piece) return
          sseBuffer += piece
          const blocks = sseBuffer.split('\n\n')
          sseBuffer = blocks.pop() || ''
          blocks.forEach((b) => {
            if (b.trim()) dispatchBlock(b)
          })
        })
      }
    }

    startAttempt(false)
  })

  return {
    promise,
    abort() {
      aborted = true
      if (requestTask && typeof requestTask.abort === 'function') {
        requestTask.abort()
      }
    },
  }
}

module.exports = {
  createUtf8StreamDecoder,
  streamSseRequest,
}
