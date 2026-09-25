import { describe, expect, it } from 'vitest'

import {
  containRect,
  pointerPosition,
} from '@/components/ComputerAppViewer/computerAppGeometry'

describe('computer app preview geometry', () => {
  it('letterboxes a wide app inside a taller card', () => {
    expect(containRect({ width: 400, height: 400 }, { width: 1600, height: 800 })).toEqual({
      left: 0,
      top: 100,
      width: 400,
      height: 200,
    })
  })

  it('pillarboxes a tall app inside a wider card', () => {
    expect(containRect({ width: 600, height: 300 }, { width: 500, height: 1000 })).toEqual({
      left: 225,
      top: 0,
      width: 150,
      height: 300,
    })
  })

  it('maps a pointer fraction onto the visible picture, not the bars', () => {
    const box = { width: 400, height: 400 }
    const content = { width: 1600, height: 800 }
    expect(pointerPosition(box, content, { x: 0.5, y: 0.5 })).toEqual({ x: 200, y: 200 })
    expect(pointerPosition(box, content, { x: 0, y: 0 })).toEqual({ x: 0, y: 100 })
    expect(pointerPosition(box, content, { x: 1, y: 1 })).toEqual({ x: 400, y: 300 })
  })

  it('clamps pointers that fall outside the window', () => {
    const box = { width: 200, height: 100 }
    const content = { width: 200, height: 100 }
    expect(pointerPosition(box, content, { x: -1, y: 3 })).toEqual({ x: 0, y: 100 })
    expect(pointerPosition(box, content, { x: Number.NaN, y: 0.5 })).toEqual({ x: 100, y: 50 })
  })

  it('degrades to the whole box before the first frame arrives', () => {
    expect(containRect({ width: 300, height: 200 }, { width: 0, height: 0 })).toEqual({
      left: 0,
      top: 0,
      width: 300,
      height: 200,
    })
  })
})
