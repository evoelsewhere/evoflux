import { translateText } from './catalog'
import type { AppLocale } from './locale'

const LOCALIZED_ATTRIBUTES = ['alt', 'aria-description', 'aria-label', 'placeholder', 'title'] as const
const IGNORE_SELECTOR = [
  '[data-i18n-ignore]',
  '[data-i18n="off"]',
  '[contenteditable="true"]',
  'code',
  'kbd',
  'pre',
  'samp',
  'script',
  'style',
  'textarea',
  '.monaco-editor',
].join(',')

interface LocalizedState {
  original: string
  translated: string
}

const textState = new WeakMap<Text, LocalizedState>()
const attributeState = new WeakMap<Element, Map<string, LocalizedState>>()

function ignored(node: Node): boolean {
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement
  return Boolean(element?.closest(IGNORE_SELECTOR))
}

function localizeTextNode(node: Text, locale: AppLocale): void {
  if (ignored(node)) return
  const current = node.nodeValue ?? ''
  const prior = textState.get(node)
  const original = prior && current === prior.translated ? prior.original : current
  const translated = translateText(original, locale)
  textState.set(node, { original, translated })
  if (translated !== current) node.nodeValue = translated
}

function localizeAttribute(element: Element, attribute: string, locale: AppLocale): void {
  if (ignored(element)) return
  const current = element.getAttribute(attribute)
  if (current == null) return
  const states = attributeState.get(element) ?? new Map<string, LocalizedState>()
  const prior = states.get(attribute)
  const original = prior && current === prior.translated ? prior.original : current
  const translated = translateText(original, locale)
  states.set(attribute, { original, translated })
  attributeState.set(element, states)
  if (translated !== current) element.setAttribute(attribute, translated)
}

function localizeElement(element: Element, locale: AppLocale): void {
  for (const attribute of LOCALIZED_ATTRIBUTES) localizeAttribute(element, attribute, locale)
}

export function localizeSubtree(root: Node, locale: AppLocale): void {
  if (ignored(root)) return
  if (root.nodeType === Node.TEXT_NODE) {
    localizeTextNode(root as Text, locale)
    return
  }
  if (root.nodeType === Node.ELEMENT_NODE) localizeElement(root as Element, locale)

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
  let current = walker.nextNode()
  while (current) {
    if (current.nodeType === Node.TEXT_NODE) localizeTextNode(current as Text, locale)
    else localizeElement(current as Element, locale)
    current = walker.nextNode()
  }
}

export function observeLocalizedDom(root: Node, locale: AppLocale): () => void {
  localizeSubtree(root, locale)
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') localizeSubtree(mutation.target, locale)
      if (mutation.type === 'attributes' && mutation.attributeName) {
        localizeAttribute(mutation.target as Element, mutation.attributeName, locale)
      }
      mutation.addedNodes.forEach((node) => localizeSubtree(node, locale))
    }
  })
  observer.observe(root, {
    attributes: true,
    attributeFilter: [...LOCALIZED_ATTRIBUTES],
    characterData: true,
    childList: true,
    subtree: true,
  })
  return () => observer.disconnect()
}
