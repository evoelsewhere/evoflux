import React from 'react'

interface IconProps {
  size?: number
  color?: string
  style?: React.CSSProperties
}

const s = (size: number, color: string, style?: React.CSSProperties): React.CSSProperties => ({
  width: size,
  height: size,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
  color,
  ...style
})

export function NodeStartIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke={color} strokeWidth="1.5" />
      <path d="M6.5 5L11 8L6.5 11V5Z" fill={color} />
    </svg>
  )
}

export function NodeEndIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke={color} strokeWidth="1.5" />
      <rect x="5" y="5" width="6" height="6" rx="1" fill={color} />
    </svg>
  )
}

export function NodeLLMIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M8 2L2 6V10L8 14L14 10V6L8 2Z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
      <circle cx="8" cy="8" r="2" fill={color} />
    </svg>
  )
}

export function NodeCodeIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <polyline points="5.5,4.5 2,8 5.5,11.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="10.5,4.5 14,8 10.5,11.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="9" y1="3" x2="7" y2="13" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

export function NodeConditionIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M8 2L14 8L8 14L2 8L8 2Z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
}

export function NodeHTTPIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke={color} strokeWidth="1.3" />
      <ellipse cx="8" cy="8" rx="3" ry="6" stroke={color} strokeWidth="1.2" />
      <line x1="2" y1="8" x2="14" y2="8" stroke={color} strokeWidth="1.2" />
    </svg>
  )
}

export function NodeTemplateIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <rect x="2" y="2" width="12" height="12" rx="2" stroke={color} strokeWidth="1.3" />
      <line x1="5" y1="5.5" x2="11" y2="5.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
      <line x1="5" y1="8" x2="9" y2="8" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
      <line x1="5" y1="10.5" x2="11" y2="10.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

export function NodeLoopIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M2 8C2 4.7 4.7 2 8 2C11.3 2 14 4.7 14 8" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
      <path d="M11 6L14 8L11 10" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function NodeMergeIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <line x1="4" y1="4" x2="8" y2="8" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
      <line x1="4" y1="12" x2="8" y2="8" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
      <line x1="8" y1="8" x2="14" y2="8" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

export function NodeDatabaseIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <ellipse cx="8" cy="4" rx="5" ry="2" stroke={color} strokeWidth="1.3" />
      <path d="M3 4V12C3 13.1 5.2 14 8 14C10.8 14 13 13.1 13 12V4" stroke={color} strokeWidth="1.3" />
      <path d="M3 8C3 9.1 5.2 10 8 10C10.8 10 13 9.1 13 8" stroke={color} strokeWidth="1.2" />
    </svg>
  )
}

export function NodeAgentIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="5" r="3" stroke={color} strokeWidth="1.3" />
      <path d="M3 14C3 11.2 5.2 9 8 9C10.8 9 13 11.2 13 14" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

export function NodeTeamIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="6" cy="5" r="2.5" stroke={color} strokeWidth="1.2" />
      <path d="M1.5 13C1.5 10.5 3.5 8.5 6 8.5C7.5 8.5 8.8 9.2 9.5 10.3" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
      <circle cx="11.5" cy="5.5" r="2" stroke={color} strokeWidth="1.1" />
      <path d="M14 12.5C14 10.6 12.6 9 11 9" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  )
}

export function NodeFolderIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M2 4C2 3.4 2.4 3 3 3H6.5L8 5H13C13.6 5 14 5.4 14 6V12C14 12.6 13.6 13 13 13H3C2.4 13 2 12.6 2 12V4Z" stroke={color} strokeWidth="1.3" />
    </svg>
  )
}

export function NodeClockIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke={color} strokeWidth="1.3" />
      <polyline points="8,4 8,8 11,10" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function NodeGlobeIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke={color} strokeWidth="1.3" />
      <path d="M2 8H14" stroke={color} strokeWidth="1.1" />
      <path d="M8 2C10 4.5 10 11.5 8 14" stroke={color} strokeWidth="1.1" />
      <path d="M8 2C6 4.5 6 11.5 8 14" stroke={color} strokeWidth="1.1" />
    </svg>
  )
}

export function NodeToolIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M10 2L14 6L8 12H4V8L10 2Z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
      <line x1="6" y1="10" x2="8" y2="8" stroke={color} strokeWidth="1.2" />
    </svg>
  )
}

export function NodeExtractIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke={color} strokeWidth="1.3" />
      <circle cx="8" cy="8" r="2" stroke={color} strokeWidth="1.2" />
      <line x1="8" y1="2" x2="8" y2="4" stroke={color} strokeWidth="1.2" />
      <line x1="8" y1="12" x2="8" y2="14" stroke={color} strokeWidth="1.2" />
    </svg>
  )
}

export function NodeTagIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M2 3L8 2L14 3V9L8 14L2 9V3Z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
      <circle cx="8" cy="7" r="1.5" fill={color} />
    </svg>
  )
}

export function NodeEditIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <path d="M11.5 2.5L13.5 4.5L5 13H3V11L11.5 2.5Z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
}

export function NodeCommentIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <rect x="2" y="2" width="12" height="10" rx="2" stroke={color} strokeWidth="1.3" />
      <line x1="5" y1="5.5" x2="11" y2="5.5" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
      <line x1="5" y1="8" x2="9" y2="8" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
      <path d="M6 12L8 14L10 12" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function NodeSubWorkflowIcon({ size = 14, color = 'currentColor' }: IconProps) {
  return (
    <svg style={s(size, color)} viewBox="0 0 16 16" fill="none">
      <rect x="1" y="1" width="6" height="6" rx="1" stroke={color} strokeWidth="1.2" />
      <rect x="9" y="1" width="6" height="6" rx="1" stroke={color} strokeWidth="1.2" />
      <rect x="5" y="9" width="6" height="6" rx="1" stroke={color} strokeWidth="1.2" />
      <line x1="4" y1="7" x2="4" y2="9" stroke={color} strokeWidth="1.1" />
      <line x1="12" y1="7" x2="12" y2="9" stroke={color} strokeWidth="1.1" />
      <line x1="4" y1="9" x2="5" y2="9" stroke={color} strokeWidth="1.1" />
      <line x1="11" y1="9" x2="12" y2="9" stroke={color} strokeWidth="1.1" />
    </svg>
  )
}
