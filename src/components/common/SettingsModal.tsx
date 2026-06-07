import { useState, useEffect } from 'react'
import { Modal, Input, Select, Button, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useSettingsStore } from '../../stores/settingsStore'

interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

export default function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { aiProvider, openaiApiKey, ollamaUrl, selectedModel, setAiProvider, setOpenaiApiKey, setOllamaUrl, setSelectedModel } = useSettingsStore()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [models, setModels] = useState<string[]>([])

  useEffect(() => { if (open) loadModels() }, [open, aiProvider])

  const loadModels = async () => { try { setModels(await window.api.ai.listModels(aiProvider)) } catch { setModels([]) } }

  const handleTestConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const result = await window.api.ai.testConnection(aiProvider)
      setTestResult(result); message[result ? 'success' : 'error'](result ? 'Connected' : 'Connection failed')
    } catch { setTestResult(false); message.error('Connection failed') }
    finally { setTesting(false) }
  }

  const labelStyle: React.CSSProperties = { color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 6, display: 'block' }

  return (
    <Modal title={<span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>Settings</span>} open={open} onCancel={onClose} footer={null} width={440}>
      <div style={{ paddingTop: 16 }}>
        <div style={{ marginBottom: 16 }}><label style={labelStyle}>AI Provider</label><Select value={aiProvider} onChange={(v) => { setAiProvider(v); setTestResult(null) }} options={[{ label: 'OpenAI', value: 'openai' }, { label: 'Ollama (Local)', value: 'ollama' }]} style={{ width: '100%' }} /></div>
        {aiProvider === 'openai' ? (
          <div style={{ marginBottom: 16 }}><label style={labelStyle}>API Key</label><Input.Password value={openaiApiKey} onChange={(e) => setOpenaiApiKey(e.target.value)} placeholder="sk-..." /></div>
        ) : (
          <div style={{ marginBottom: 16 }}><label style={labelStyle}>Ollama URL</label><Input value={ollamaUrl} onChange={(e) => setOllamaUrl(e.target.value)} placeholder="http://localhost:11434" /></div>
        )}
        <div style={{ marginBottom: 20 }}><label style={labelStyle}>Model</label><Select value={selectedModel} onChange={setSelectedModel} options={models.map((m) => ({ label: m, value: m }))} placeholder="Select a model" showSearch style={{ width: '100%' }} /></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button onClick={handleTestConnection} loading={testing} style={{ height: 36 }}>{testing ? 'Testing...' : 'Test Connection'}</Button>
          {testResult !== null && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: testResult ? 'var(--success)' : 'var(--error)' }}>
              {testResult ? <CheckCircleOutlined /> : <CloseCircleOutlined />} {testResult ? 'Connected' : 'Failed'}
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}
