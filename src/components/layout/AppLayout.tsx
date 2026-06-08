import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import SettingsPopup from '../settings/SettingsPopup'

const { Content } = Layout

export default function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <div className="titlebar-drag" style={{ position: 'fixed', top: 0, left: 0, right: 0, height: 38, zIndex: 9998 }} />
      <Sidebar />
      <Content style={{ margin: 0, paddingTop: 38, overflow: 'hidden', background: 'var(--bg-primary)' }}>
        <Outlet />
      </Content>
      <SettingsPopup />
    </Layout>
  )
}

export function EditorLayout() {
  return (
    <>
      <div className="titlebar-drag" style={{ position: 'fixed', top: 0, left: 0, right: 0, height: 38, zIndex: 9998 }} />
      <Outlet />
      <SettingsPopup />
    </>
  )
}
