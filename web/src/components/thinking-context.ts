import { createContext } from 'react'

/**
 * True inside an activity group that holds only reasoning. The group's own
 * summary row already reads "Thought", so a second "Thought · N chars" toggle
 * under it is a redundant click; the trace renders as plain body instead, and
 * the group's bounded log does the scrolling.
 */
export const ThinkingHeaderlessContext = createContext(false)
