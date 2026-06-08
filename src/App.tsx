import { Routes, Route } from 'react-router-dom'
import AppLayout, { EditorLayout } from './components/layout/AppLayout'
import Dashboard from './components/dashboard/Dashboard'
import WorkflowEditor from './components/workflow/WorkflowEditor'
import ErrorBoundary from './components/common/ErrorBoundary'

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        {/* Routes with nav sidebar */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/workflows" element={<Dashboard />} />
        </Route>

        {/* Workflow editor — own sidebar, no nav sidebar */}
        <Route element={<EditorLayout />}>
          <Route path="/workflows/:id" element={<WorkflowEditor />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
