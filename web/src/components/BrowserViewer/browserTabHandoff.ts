/**
 * Moving a live page from one surface to another.
 *
 * "Open in the browser panel" used to mean opening the *address* in the
 * panel: a second WebView, a second load, and everything the first one had
 * accumulated — the scroll position, the form half filled in, the session
 * the agent had signed into — gone. The page is a native child WebView of
 * the app's window, and the panel is another box in that same window, so
 * nothing about the page has to be thrown away to show it there. Only the
 * bookkeeping has to move.
 *
 * So the surface letting go stops managing the WebView without closing it,
 * and leaves its label here for the surface picking it up. The offer names
 * the workbench tab it was made for, because a WebView adopted by the wrong
 * surface is a page that vanishes from one panel and appears in another.
 */

export interface BrowserTabOffer {
  /** The native WebView's label — the only handle another surface needs. */
  label: string
  /** What the page is showing, so the receiving surface can label it. */
  url: string
}

interface PendingOffer extends BrowserTabOffer {
  sessionId: string
  instanceId: string
  timer: ReturnType<typeof setTimeout>
}

/**
 * Long enough for a workbench tab to mount and ask for its page, short
 * enough that an offer nobody collected cannot strand a later tab with a
 * WebView showing something it never asked for.
 */
const OFFER_TTL_MS = 30_000

let pending: PendingOffer | null = null

export function offerBrowserTab(
  sessionId: string,
  instanceId: string,
  offer: BrowserTabOffer,
): void {
  abandon()
  pending = {
    ...offer,
    sessionId,
    instanceId,
    // Nobody owns a WebView between the two surfaces. If the panel never
    // opens — the tab is closed first, the browser is switched off — an
    // uncollected page would sit over the app forever, visible, with no
    // panel able to move, hide or close it. Better a page that closes than
    // one nothing can reach.
    timer: setTimeout(abandon, OFFER_TTL_MS),
  }
}

/** Take the offer made to this surface, if there is one. */
export function claimBrowserTab(
  sessionId: string,
  instanceId: string,
): BrowserTabOffer | null {
  const offer = pending
  if (!offer) return null
  if (offer.sessionId !== sessionId || offer.instanceId !== instanceId) return null
  clearTimeout(offer.timer)
  pending = null
  return { label: offer.label, url: offer.url }
}

function abandon(): void {
  const offer = pending
  if (!offer) return
  clearTimeout(offer.timer)
  pending = null
  void import('@tauri-apps/api/webview')
    .then(({ Webview }) => Webview.getByLabel(offer.label))
    .then((webview) => webview?.close())
    .catch(() => {
      // Nothing left to close, or no desktop shell to close it with.
    })
}
