import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from 'antd'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          height: '100%', padding: 40, background: 'var(--bg-primary)'
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <h2 style={{ color: 'var(--text-primary)', fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
            Something went wrong
          </h2>
          <p style={{ color: 'var(--text-tertiary)', fontSize: 13, marginBottom: 24, textAlign: 'center', maxWidth: 400 }}>
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>
          <Button type="primary" onClick={() => this.setState({ hasError: false, error: null })}>
            Try Again
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}
