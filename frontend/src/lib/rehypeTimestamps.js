import { visit } from 'unist-util-visit'

const TIMESTAMP_RE = /\b(\d{2}:\d{2}:\d{2})\b/g

// Rehype plugin: replace HH:MM:SS text nodes with custom <timestamp value="…"> elements.
// Skips text already inside <a>, <code>, or <pre> to avoid mangling links/code.
export default function rehypeTimestamps() {
  return (tree) => {
    visit(tree, 'text', (node, index, parent) => {
      if (!parent || index == null) return

      const skipTags = new Set(['a', 'code', 'pre'])
      if (parent.type === 'element' && skipTags.has(parent.tagName)) return

      const text = node.value
      if (!TIMESTAMP_RE.test(text)) return
      TIMESTAMP_RE.lastIndex = 0

      const newNodes = []
      let last = 0
      let match

      while ((match = TIMESTAMP_RE.exec(text)) !== null) {
        if (match.index > last) {
          newNodes.push({ type: 'text', value: text.slice(last, match.index) })
        }
        newNodes.push({
          type: 'element',
          tagName: 'timestamp',
          properties: { value: match[1] },
          children: [{ type: 'text', value: match[1] }],
        })
        last = TIMESTAMP_RE.lastIndex
      }

      if (last < text.length) {
        newNodes.push({ type: 'text', value: text.slice(last) })
      }

      parent.children.splice(index, 1, ...newNodes)
      return index + newNodes.length
    })
  }
}
