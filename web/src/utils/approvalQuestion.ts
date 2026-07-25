function decodeJsonStringFragment(value: string): string {
  let decoded = ''
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]
    if (character !== '\\') {
      decoded += character
      continue
    }

    const escape = value[index + 1]
    if (escape === undefined) break
    index += 1
    if (escape === 'n') decoded += '\n'
    else if (escape === 'r') decoded += '\r'
    else if (escape === 't') decoded += '\t'
    else if (escape === 'b') decoded += '\b'
    else if (escape === 'f') decoded += '\f'
    else if (escape === '"' || escape === '\\' || escape === '/') decoded += escape
    else if (escape === 'u') {
      const codePoint = value.slice(index + 1, index + 5)
      if (!/^[\da-f]{4}$/i.test(codePoint)) break
      decoded += String.fromCharCode(Number.parseInt(codePoint, 16))
      index += 4
    }
  }
  return decoded
}

function extractTextBlocks(value: string): string | null {
  try {
    const parsed: unknown = JSON.parse(value)
    const blocks = Array.isArray(parsed) ? parsed : [parsed]
    const text = blocks
      .map((block) => {
        if (typeof block === 'string') return block
        if (block === null || typeof block !== 'object' || !('text' in block)) return ''
        return typeof block.text === 'string' ? block.text : ''
      })
      .filter(Boolean)

    return text.length > 0 ? text.join('\n\n') : null
  } catch {
    const prefix = /^\s*\[\s*\{\s*"text"\s*:\s*"/.exec(value)
    if (!prefix) return null

    const encoded = value.slice(prefix[0].length)
    let escaped = false
    let end = encoded.length
    for (let index = 0; index < encoded.length; index += 1) {
      const character = encoded[index]
      if (escaped) escaped = false
      else if (character === '\\') escaped = true
      else if (character === '"') {
        end = index
        break
      }
    }
    return decodeJsonStringFragment(encoded.slice(0, end)) || null
  }
}

export function formatApprovalQuestion(question: string): string {
  const separator = question.indexOf('\n\n')
  const title = separator >= 0 ? question.slice(0, separator) : ''
  const body = separator >= 0 ? question.slice(separator + 2) : question
  const text = extractTextBlocks(body.trim())
  if (!text) return question
  return title ? `${title}\n\n${text}` : text
}