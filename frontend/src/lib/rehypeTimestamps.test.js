import { describe, expect, it } from 'vitest'
import rehypeTimestamps from './rehypeTimestamps.js'

function makeTree(text, tagName = 'p') {
  return {
    type: 'root',
    children: [
      {
        type: 'element',
        tagName,
        properties: {},
        children: [{ type: 'text', value: text }],
      },
    ],
  }
}

function runPlugin(tree) {
  rehypeTimestamps()(tree)
  return tree
}

describe('rehypeTimestamps plugin', () => {
  it('splits a single timestamp from surrounding text', () => {
    const tree = runPlugin(makeTree('See 00:01:23 in the call'))
    const children = tree.children[0].children
    expect(children).toHaveLength(3)
    expect(children[0]).toEqual({ type: 'text', value: 'See ' })
    expect(children[1]).toMatchObject({
      type: 'element',
      tagName: 'timestamp',
      properties: { value: '00:01:23' },
      children: [{ type: 'text', value: '00:01:23' }],
    })
    expect(children[2]).toEqual({ type: 'text', value: ' in the call' })
  })

  it('handles a timestamp at the start of text', () => {
    const tree = runPlugin(makeTree('00:00:00 start'))
    const children = tree.children[0].children
    expect(children[0]).toMatchObject({ type: 'element', tagName: 'timestamp' })
    expect(children[1]).toEqual({ type: 'text', value: ' start' })
  })

  it('handles a timestamp at the end of text', () => {
    const tree = runPlugin(makeTree('end at 00:59:59'))
    const children = tree.children[0].children
    expect(children[children.length - 1]).toMatchObject({ type: 'element', tagName: 'timestamp' })
  })

  it('handles multiple timestamps in one text node', () => {
    const tree = runPlugin(makeTree('At 00:01:00 and 00:02:00 exactly'))
    const timestamps = tree.children[0].children.filter(
      (n) => n.type === 'element' && n.tagName === 'timestamp',
    )
    expect(timestamps).toHaveLength(2)
    expect(timestamps[0].properties.value).toBe('00:01:00')
    expect(timestamps[1].properties.value).toBe('00:02:00')
  })

  it('leaves text with no timestamps unchanged', () => {
    const tree = runPlugin(makeTree('No timestamps here'))
    const children = tree.children[0].children
    expect(children).toHaveLength(1)
    expect(children[0]).toEqual({ type: 'text', value: 'No timestamps here' })
  })

  it('does not split text inside <code> elements', () => {
    const tree = {
      type: 'root',
      children: [
        {
          type: 'element',
          tagName: 'code',
          properties: {},
          children: [{ type: 'text', value: '00:01:23' }],
        },
      ],
    }
    runPlugin(tree)
    expect(tree.children[0].children[0].type).toBe('text')
    expect(tree.children[0].children[0].value).toBe('00:01:23')
  })

  it('does not split text inside <a> elements', () => {
    const tree = {
      type: 'root',
      children: [
        {
          type: 'element',
          tagName: 'a',
          properties: { href: '#' },
          children: [{ type: 'text', value: 'link 00:01:23' }],
        },
      ],
    }
    runPlugin(tree)
    expect(tree.children[0].children[0].type).toBe('text')
  })

  it('does not split text inside <pre> elements', () => {
    const tree = {
      type: 'root',
      children: [
        {
          type: 'element',
          tagName: 'pre',
          properties: {},
          children: [{ type: 'text', value: 'code 00:01:23' }],
        },
      ],
    }
    runPlugin(tree)
    expect(tree.children[0].children[0].type).toBe('text')
  })
})
