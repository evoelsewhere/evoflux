import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

const { Content } = Layout

export default function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Sidebar />
      <Content style={{ margin: 0, overflow: 'hidden', background: 'var(--bg-primary)' }}>
        <Outlet />
      </Content>
    </Layout>
  )
}

export function EditorLayout() {
  return <Outlet />
}
