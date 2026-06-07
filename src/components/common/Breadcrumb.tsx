import { useNavigate, useLocation } from 'react-router-dom'
import { RightOutlined, HomeOutlined } from '@ant-design/icons'

const routeLabels: Record<string, string> = {
  '/': 'Dashboard',
  '/workflows': 'Workflows',
  '/knowledge': 'Knowledge Base',
  '/tools': 'Tools',
  '/settings': 'Settings'
}

export default function Breadcrumb({ extra }: { extra?: string }) {
  const navigate = useNavigate()
  const location = useLocation()

  const pathParts = location.pathname.split('/').filter(Boolean)
  const crumbs: { label: string; path: string }[] = [
    { label: 'Dashboard', path: '/' }
  ]

  let currentPath = ''
  for (const part of pathParts) {
    currentPath += `/${part}`
    const label = routeLabels[currentPath] || (extra && currentPath === location.pathname ? extra : part)
    crumbs.push({ label, path: currentPath })
  }

  if (crumbs.length <= 1) return null

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '12px 24px',
      borderBottom: '1px solid var(--border-primary)',
      background: 'var(--bg-secondary)'
    }}>
      <HomeOutlined
        style={{ color: 'var(--text-tertiary)', fontSize: 12, cursor: 'pointer' }}
        onClick={() => navigate('/')}
      />
      {crumbs.map((crumb, i) => (
        <div key={crumb.path} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <RightOutlined style={{ color: 'var(--text-tertiary)', fontSize: 9 }} />
          <span
            onClick={() => i < crumbs.length - 1 && navigate(crumb.path)}
            style={{
              fontSize: 13,
              fontWeight: i === crumbs.length - 1 ? 500 : 400,
              color: i === crumbs.length - 1 ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: i < crumbs.length - 1 ? 'pointer' : 'default',
              transition: 'color 0.1s'
            }}
            onMouseEnter={(e) => {
              if (i < crumbs.length - 1) e.currentTarget.style.color = 'var(--text-primary)'
            }}
            onMouseLeave={(e) => {
              if (i < crumbs.length - 1) e.currentTarget.style.color = 'var(--text-secondary)'
            }}
          >
            {crumb.label}
          </span>
        </div>
      ))}
    </div>
  )
}
