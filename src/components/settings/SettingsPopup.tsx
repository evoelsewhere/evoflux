import { useState, useRef } from 'react'
import { Button, Input, Select, Slider, message, Popconfirm, Switch } from 'antd'
import { PlusOutlined, DeleteOutlined, StarOutlined, StarFilled, CheckCircleOutlined, CloseCircleOutlined, EditOutlined } from '@ant-design/icons'
import { useProviderStore, PROVIDER_LABELS, PROVIDER_TEMPLATES, type ProviderType, type ProviderInstance } from '../../stores/providerStore'
import { useSettingsStore, ACCENT_PRESETS, FONT_SIZE_MAP, FONT_FAMILY_MAP, type FontSize, type FontFamily } from '../../stores/settingsStore'

const PROVIDER_TYPES: ProviderType[] = ['openai', 'anthropic', 'ollama', 'openai-compatible', 'claude-cli', 'copilot-cli']

export default function SettingsPopup() {
  const { showSettings, setShowSettings } = useSettingsStore()
  const { providers, addProvider, updateProvider, removeProvider, setDefault } = useProviderStore()
  const { appearance, updateAppearance } = useSettingsStore()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, boolean>>({})
  const [addType, setAddType] = useState<ProviderType>('openai')
  const [activeTab, setActiveTab] = useState<'providers' | 'appearance' | 'about'>('providers')
  const containerRef = useRef<HTMLDivElement>(null)

  if (!showSettings) return null

  const handleAdd = () => {
    const id = addProvider(addType)
    setEditingId(id)
  }

  const handleTest = async (p: ProviderInstance) => {
    setTesting(p.id); setTestResult(r => ({ ...r, [p.id]: undefined as unknown as boolean }))
    try {
      const result = await window.api.ai.testConnection(p.type, { apiKey: p.apiKey, baseUrl: p.baseUrl })
      setTestResult(r => ({ ...r, [p.id]: result }))
      message[result ? 'success' : 'error'](`${p.name}: ${result ? 'Connected' : 'Failed'}`)
    } catch { setTestResult(r => ({ ...r, [p.id]: false })); message.error(`${p.name}: Failed`) }
    finally { setTesting(null) }
  }

  const labelStyle: React.CSSProperties = { color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4, display: 'block' }

  const tabs = [
    { key: 'providers' as const, label: 'AI Providers' },
    { key: 'appearance' as const, label: 'Appearance' },
    { key: 'about' as const, label: 'About' }
  ]

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)'
      }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) setShowSettings(false) }}
    >
      <div ref={containerRef} style={{
        width: 640, maxHeight: 'calc(100vh - 80px)',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-primary)',
        borderRadius: 16,
        boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden'
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '14px 20px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Settings</span>
            <div style={{ display: 'flex', gap: 2 }}>
              {tabs.map(t => (
                <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
                  padding: '4px 12px', fontSize: 12, fontWeight: 500, borderRadius: 6,
                  background: activeTab === t.key ? 'var(--accent-muted)' : 'transparent',
                  border: activeTab === t.key ? '1px solid var(--accent)' : '1px solid transparent',
                  color: activeTab === t.key ? 'var(--accent)' : 'var(--text-tertiary)',
                  cursor: 'pointer', transition: 'all 0.15s'
                }}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <button onClick={() => setShowSettings(false)} aria-label="Close settings" style={{
            width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
            borderRadius: 6, fontSize: 18, lineHeight: 1, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {activeTab === 'providers' && (
            <section>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>AI Providers</h2>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Select value={addType} onChange={setAddType} size="small" style={{ width: 160 }}
                    getPopupContainer={() => containerRef.current!}
                    options={PROVIDER_TYPES.map(t => ({ label: PROVIDER_LABELS[t], value: t }))} />
                  <Button type="primary" icon={<PlusOutlined />} size="small" onClick={handleAdd}>Add</Button>
                </div>
              </div>

              {providers.length === 0 && (
                <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 12, padding: 32, textAlign: 'center' }}>
                  <div style={{ fontSize: 13, color: 'var(--text-tertiary)', marginBottom: 12 }}>No AI providers configured</div>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => { addProvider('openai'); setEditingId(providers[0]?.id || null) }}>
                    Add your first provider
                  </Button>
                </div>
              )}

              {providers.map((p) => {
                const isEditing = editingId === p.id
                return (
                  <div key={p.id} style={{
                    background: 'var(--bg-card)', border: `1px solid ${p.isDefault ? 'var(--accent)' : 'var(--border-primary)'}`,
                    borderRadius: 10, marginBottom: 10, overflow: 'hidden',
                    boxShadow: p.isDefault ? '0 0 0 1px var(--accent-muted)' : 'none'
                  }}>
                    <div style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '10px 14px', cursor: 'pointer', transition: 'background 0.1s'
                    }} onClick={() => setEditingId(isEditing ? null : p.id)}
                       onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                       onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: 7,
                          background: p.isDefault ? 'var(--accent-muted)' : 'var(--bg-secondary)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700,
                          color: p.isDefault ? 'var(--accent)' : 'var(--text-tertiary)'
                        }}>
                          {p.name.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                            {p.name}
                            {p.isDefault && <span style={{ fontSize: 8, background: 'var(--accent-muted)', color: 'var(--accent)', padding: '1px 5px', borderRadius: 4 }}>DEFAULT</span>}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>
                            {PROVIDER_LABELS[p.type]} &middot; {p.defaultModel || 'No model set'}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 2 }}>
                        {!p.isDefault && (
                          <button onClick={(e) => { e.stopPropagation(); setDefault(p.id) }}
                            style={{ width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', borderRadius: 4 }}
                            title="Set as default">
                            <StarOutlined style={{ fontSize: 12 }} />
                          </button>
                        )}
                        <button onClick={(e) => { e.stopPropagation(); setEditingId(p.id) }}
                          style={{ width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', borderRadius: 4 }}>
                          <EditOutlined style={{ fontSize: 12 }} />
                        </button>
                        <Popconfirm title={`Delete ${p.name}?`} onConfirm={() => removeProvider(p.id)} okText="Delete" cancelText="Cancel" okButtonProps={{ danger: true }}
                          getPopupContainer={() => containerRef.current!}>
                          <button onClick={(e) => e.stopPropagation()}
                            style={{ width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)', borderRadius: 4 }}>
                            <DeleteOutlined style={{ fontSize: 12 }} />
                          </button>
                        </Popconfirm>
                      </div>
                    </div>

                    {isEditing && (
                      <div style={{ padding: '0 14px 14px', borderTop: '1px solid var(--border-primary)' }}>
                        <div style={{ display: 'flex', gap: 10, marginTop: 10, marginBottom: 10 }}>
                          <div style={{ flex: 1 }}>
                            <label style={labelStyle}>Name</label>
                            <Input size="small" value={p.name} onChange={(e) => updateProvider(p.id, { name: e.target.value })} />
                          </div>
                          <div style={{ flex: 1 }}>
                            <label style={labelStyle}>Default Model</label>
                            <Input size="small" value={p.defaultModel} onChange={(e) => updateProvider(p.id, { defaultModel: e.target.value })} />
                          </div>
                        </div>

                        {(p.type === 'openai' || p.type === 'anthropic' || p.type === 'openai-compatible') && (
                          <div style={{ marginBottom: 10 }}>
                            <label style={labelStyle}>API Key</label>
                            <Input.Password size="small" value={p.apiKey} onChange={(e) => updateProvider(p.id, { apiKey: e.target.value })}
                              placeholder={p.type === 'anthropic' ? 'sk-ant-...' : 'sk-...'} />
                          </div>
                        )}

                        {(p.type === 'openai' || p.type === 'anthropic' || p.type === 'ollama' || p.type === 'openai-compatible') && (
                          <div style={{ marginBottom: 10 }}>
                            <label style={labelStyle}>Base URL</label>
                            <Input size="small" value={p.baseUrl} onChange={(e) => updateProvider(p.id, { baseUrl: e.target.value })}
                              placeholder={PROVIDER_TEMPLATES[p.type].baseUrl || 'https://...'} />
                          </div>
                        )}

                        {(p.type === 'claude-cli' || p.type === 'copilot-cli') && (
                          <div style={{ marginBottom: 10, padding: 8, background: 'var(--accent-muted)', borderRadius: 6, fontSize: 10, color: 'var(--text-secondary)' }}>
                            {p.type === 'claude-cli' && 'Install: npm install -g @anthropic-ai/claude-cli. Then: claude configure'}
                            {p.type === 'copilot-cli' && 'Install: gh extension install github/gh-copilot. Then: gh auth login'}
                          </div>
                        )}

                        <div style={{ marginBottom: 10 }}>
                          <label style={labelStyle}>Models (comma separated)</label>
                          <Input size="small" value={p.models.join(', ')}
                            onChange={(e) => updateProvider(p.id, { models: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                            placeholder="gpt-4o, gpt-4o-mini" />
                        </div>

                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <Button size="small" onClick={() => handleTest(p)} loading={testing === p.id}>
                            Test Connection
                          </Button>
                          {testResult[p.id] !== undefined && (
                            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: testResult[p.id] ? 'var(--success)' : 'var(--error)' }}>
                              {testResult[p.id] ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                              {testResult[p.id] ? 'Connected' : 'Failed'}
                            </span>
                          )}
                          {!p.isDefault && (
                            <Button size="small" icon={<StarFilled />} onClick={() => setDefault(p.id)} style={{ marginLeft: 'auto' }}>
                              Set as Default
                            </Button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          )}

          {activeTab === 'appearance' && (
            <section>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 14px 0' }}>Appearance</h2>
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 10, padding: 16 }}>

                <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Theme</label>
                    <Select value={appearance.theme} onChange={(v) => updateAppearance({ theme: v })}
                      getPopupContainer={() => containerRef.current!}
                      options={[{ label: 'Dark', value: 'dark' }, { label: 'Light', value: 'light' }]} style={{ width: '100%' }} size="small" />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Compact Mode</label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 28 }}>
                      <Switch size="small" checked={appearance.compactMode} onChange={(v) => updateAppearance({ compactMode: v })} />
                      <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{appearance.compactMode ? 'On' : 'Off'}</span>
                    </div>
                  </div>
                </div>

                <div style={{ marginBottom: 16 }}>
                  <label style={labelStyle}>Accent Color</label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
                    {ACCENT_PRESETS.map((c) => (
                      <button key={c.value} onClick={() => updateAppearance({ accentColor: c.value })}
                        style={{
                          width: 24, height: 24, borderRadius: 5, cursor: 'pointer',
                          background: c.value, border: appearance.accentColor === c.value ? '2px solid var(--text-primary)' : '2px solid transparent',
                          boxShadow: appearance.accentColor === c.value ? `0 0 0 2px var(--bg-elevated), 0 0 0 4px ${c.value}` : 'none'
                        }}
                        title={c.name}
                      />
                    ))}
                  </div>
                  <Input size="small" value={appearance.accentColor} onChange={(e) => updateAppearance({ accentColor: e.target.value })}
                    placeholder="#0070f3" style={{ width: 130 }} prefix={
                      <div style={{ width: 10, height: 10, borderRadius: 3, background: appearance.accentColor, flexShrink: 0 }} />
                    } />
                </div>

                <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Font Size</label>
                    <Select value={appearance.fontSize} onChange={(v) => updateAppearance({ fontSize: v as FontSize })} style={{ width: '100%' }} size="small"
                      getPopupContainer={() => containerRef.current!}
                      options={Object.entries(FONT_SIZE_MAP).map(([k, v]) => ({ label: v.label, value: k }))} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Font Family</label>
                    <Select value={appearance.fontFamily} onChange={(v) => updateAppearance({ fontFamily: v as FontFamily })} style={{ width: '100%' }} size="small"
                      getPopupContainer={() => containerRef.current!}
                      options={Object.entries(FONT_FAMILY_MAP).map(([k, v]) => ({ label: v.label, value: k }))} />
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Node Radius: {appearance.nodeBorderRadius}px</label>
                    <Slider min={0} max={20} value={appearance.nodeBorderRadius} onChange={(v) => updateAppearance({ nodeBorderRadius: v })} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Dot Size: {appearance.canvasDotSize}</label>
                    <Slider min={0} max={4} value={appearance.canvasDotSize} onChange={(v) => updateAppearance({ canvasDotSize: v })} />
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 16 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Dot Color</label>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <Input size="small" value={appearance.canvasDotColor} onChange={(e) => updateAppearance({ canvasDotColor: e.target.value })}
                        placeholder="Auto" style={{ flex: 1 }} />
                      <button onClick={() => updateAppearance({ canvasDotColor: '' })}
                        style={{ padding: '2px 7px', fontSize: 10, borderRadius: 4, cursor: 'pointer', background: 'var(--bg-input)', border: '1px solid var(--border-primary)', color: 'var(--text-tertiary)' }}>
                        Reset
                      </button>
                    </div>
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>Sidebar: {appearance.sidebarWidth}px</label>
                    <Slider min={160} max={320} step={10} value={appearance.sidebarWidth} onChange={(v) => updateAppearance({ sidebarWidth: v })} />
                  </div>
                </div>
              </div>
            </section>
          )}

          {activeTab === 'about' && (
            <section>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 14px 0' }}>About</h2>
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 10, padding: 20 }}>
                <div style={{ fontSize: 14, color: 'var(--text-primary)', marginBottom: 6 }}>
                  <strong>Evoflux</strong> — AI Automation Workflow for SDLC
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                  Version 1.0.0 &middot; Electron + React + TypeScript
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
