import { describe, it, expect, afterEach, beforeEach } from "bun:test"
import { cleanup, render, screen } from "@testing-library/react"
import { AssistantTurnFooter } from "@/components/AssistantTurnFooter"
import type { ContentBlock } from "@/api/types"

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: () => Promise.resolve() },
    configurable: true,
    writable: true,
  })
})

afterEach(cleanup)

describe("AssistantTurnFooter", () => {
  it("shows response duration after copy, continue, and timestamp controls", () => {
    const blocks: ContentBlock[] = [{
      id: "b1",
      type: "text",
      content: "Assistant answer",
      timestamp: new Date("2026-05-23T12:34:56Z"),
      responseDurationMs: 1234,
    }]

    render(<AssistantTurnFooter turnBlocks={blocks} onContinue={() => undefined} />)

    expect(screen.getByLabelText("Copy response")).toBeTruthy()
    expect(screen.getByLabelText("Continue response")).toBeTruthy()
    expect(screen.getByText("12:34")).toBeTruthy()
    expect(screen.getByTitle("Response duration").textContent).toBe("1.2s")
  })

  it("shows long response durations as minutes and seconds", () => {
    const blocks: ContentBlock[] = [{
      id: "b1",
      type: "text",
      content: "Assistant answer",
      responseDurationMs: 93_000,
    }]

    render(<AssistantTurnFooter turnBlocks={blocks} />)

    expect(screen.getByTitle("Response duration").textContent).toBe("1m 33s")
  })
})
