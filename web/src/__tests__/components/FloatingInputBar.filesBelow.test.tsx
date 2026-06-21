import { describe, it, expect, afterEach, beforeEach } from "bun:test"
import { useRef } from "react"
import { render, screen, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FloatingInputBar } from "@/components/FloatingInputBar"

afterEach(cleanup)
beforeEach(() => {})

function Harness(props: {
  onSubmit?: (message: string, files?: File[]) => void
  placeholder?: string
}) {
  const boundsRef = useRef<HTMLDivElement>(null)
  return (
    <div
      ref={boundsRef}
      data-testid="bounds"
      style={{ position: "relative", width: 1200, height: 800 }}
    >
      <FloatingInputBar
        boundsRef={boundsRef}
        onSubmit={props.onSubmit ?? (() => {})}
        placeholder={props.placeholder ?? "Message…"}
      />
    </div>
  )
}

describe("FloatingInputBar.fileUpload", () => {
  it("renders file preview after upload", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const file = new File(["test"], "test.txt", { type: "text/plain" })
    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(hiddenInput, file)

    const fileText = await screen.findByText("test.txt")
    expect(fileText).toBeTruthy()
  })
})
