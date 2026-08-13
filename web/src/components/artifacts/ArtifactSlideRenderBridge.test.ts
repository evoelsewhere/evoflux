import { describe, expect, it } from 'vitest'
import { collectEditableElements, parseSlideColor } from './slide-editable'

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return {
    x,
    y,
    width,
    height,
    top: y,
    right: x + width,
    bottom: y + height,
    left: x,
    toJSON: () => ({}),
  }
}

describe('HTML slide editable extraction', () => {
  it('normalizes opaque CSS colors', () => {
    expect(parseSlideColor('rgb(17, 34, 51)')).toBe('#112233')
    expect(parseSlideColor('rgba(17, 34, 51, 0.5)')).toBeNull()
  })

  it('keeps simple text editable and flattens unsupported effects', () => {
    document.body.innerHTML = `
      <section data-slide-root>
        <h1 data-pptx-editable="text" style="font: 700 48px/1 Arial; color: rgb(255, 255, 255)">Editable title</h1>
        <p data-pptx-editable="text" style="font: 24px Arial; color: black; text-shadow: 1px 1px black">Flatten me</p>
      </section>
    `
    const root = document.querySelector<HTMLElement>('[data-slide-root]')!
    const title = root.querySelector<HTMLElement>('h1')!
    const shadow = root.querySelector<HTMLElement>('p')!
    root.getBoundingClientRect = () => rect(0, 0, 1280, 720)
    title.getBoundingClientRect = () => rect(80, 70, 700, 64)
    shadow.getBoundingClientRect = () => rect(80, 160, 500, 40)

    const result = collectEditableElements(root, {
      request_id: 'request',
      slide_id: 'slide',
      width: 1280,
      height: 720,
      html: '',
      css: '',
      assets: {},
    })

    expect(result.issues).toHaveLength(1)
    expect(result.elements).toHaveLength(1)
    expect(result.elements[0]).toMatchObject({ kind: 'text', text: 'Editable title', font_size: 48 })
    expect(result.hidden).toEqual([title])
    expect(result.issues.some((issue) => issue.code === 'editable-text-flattened')).toBe(true)
  })

  it('exports safe rich text while flattening cropped images for fidelity', () => {
    document.body.innerHTML = `
      <section data-slide-root>
        <p data-pptx-editable="text" style="font: 32px Arial; color: black">One <strong style="color: red">accent</strong></p>
        <img data-pptx-editable="image" data-pptx-asset="photo" style="object-fit: cover" alt="Photo">
      </section>
    `
    const root = document.querySelector<HTMLElement>('[data-slide-root]')!
    const text = root.querySelector<HTMLElement>('p')!
    const image = root.querySelector<HTMLElement>('img')!
    root.getBoundingClientRect = () => rect(0, 0, 1280, 720)
    text.getBoundingClientRect = () => rect(80, 70, 700, 64)
    image.getBoundingClientRect = () => rect(80, 180, 400, 240)

    const result = collectEditableElements(root, {
      request_id: 'request',
      slide_id: 'slide',
      width: 1280,
      height: 720,
      html: '',
      css: '',
      assets: { photo: { mime_type: 'image/png', suffix: '.png' } },
    })

    expect(result.elements).toHaveLength(1)
    expect(result.elements[0]).toMatchObject({
      kind: 'text',
      paragraphs: [{
        runs: [
          { text: 'One ', color: '#000000' },
          { text: 'accent', color: '#FF0000' },
        ],
      }],
    })
    expect(result.hidden).toEqual([text])
    expect(result.issues.map((issue) => issue.code)).toEqual([
      'editable-image-flattened',
    ])
  })
})
