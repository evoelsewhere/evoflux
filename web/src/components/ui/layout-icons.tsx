import { createLucideIcon, MessageCircle } from 'lucide-react'

/**
 * Layout icons use independent rounded shapes instead of Lucide's box-heavy
 * panel glyphs. They still use the Lucide component contract, so sizing,
 * colour and accessibility stay consistent with the rest of the app.
 */
export const FocusViewIcon = MessageCircle

export const SplitViewIcon = createLucideIcon('SplitView', [
  [
    'rect',
    {
      x: '3',
      y: '4',
      width: '7',
      height: '16',
      rx: '2.5',
      key: 'left-pane',
    },
  ],
  [
    'rect',
    {
      x: '14',
      y: '4',
      width: '7',
      height: '16',
      rx: '2.5',
      key: 'right-pane',
    },
  ],
])

export const MonitorViewIcon = createLucideIcon('MonitorView', [
  ['rect', { x: '3', y: '4', width: '8', height: '7', rx: '2', key: 'top-left' }],
  ['rect', { x: '13', y: '4', width: '8', height: '7', rx: '2', key: 'top-right' }],
  ['rect', { x: '3', y: '13', width: '8', height: '7', rx: '2', key: 'bottom-left' }],
  ['rect', { x: '13', y: '13', width: '8', height: '7', rx: '2', key: 'bottom-right' }],
])

export const SidePanelIcon = createLucideIcon('SidePanel', [
  [
    'rect',
    {
      x: '3',
      y: '4',
      width: '18',
      height: '16',
      rx: '3',
      key: 'panel-frame',
    },
  ],
  ['path', { d: 'M14.5 7.5v9', key: 'panel-divider' }],
])
