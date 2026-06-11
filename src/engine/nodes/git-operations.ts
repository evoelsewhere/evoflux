import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

interface GitOpsConfig {
  repo_path?: string
  remote?: string
  base_branch?: string
  auto_push?: boolean
  create_pr?: boolean
  pr_title?: string
  pr_body?: string
}

export class GitOpsNode extends BaseNode<GitOpsConfig> {
  readonly type = 'git-operations'

  getMetadata(): NodeMetadata {
    return {
      type: 'git-operations',
      label: 'Git Operations',
      icon: 'sync',
      category: 'tools',
      description: 'Git add, commit, push, and create pull request.',
      inputs: [
        { name: 'files', label: 'Files to commit', type: 'string', required: false },
        { name: 'message', label: 'Commit message', type: 'string', required: true },
        { name: 'branch_name', label: 'Branch name', type: 'string', required: false }
      ],
      outputs: [
        { name: 'commit_hash', label: 'Commit Hash', type: 'string', required: false },
        { name: 'branch_name', label: 'Branch Name', type: 'string', required: false },
        { name: 'pr_url', label: 'PR URL', type: 'string', required: false },
        { name: 'success', label: 'Success', type: 'boolean', required: false },
        { name: 'log', label: 'Log', type: 'string', required: false }
      ],
      defaultConfig: {
        repo_path: '',
        remote: 'origin',
        base_branch: 'main',
        auto_push: true,
        create_pr: false
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as GitOpsConfig
    const repoPath = String(cfg.repo_path || '')
    const commitMessage = String(inputs.message || 'Auto-commit by coding agent')
    const files = inputs.files ? String(inputs.files).split(',').map(f => f.trim()) : ['.']
    const branchName = inputs.branch_name ? String(inputs.branch_name) : undefined
    const remote = cfg.remote || 'origin'
    const baseBranch = cfg.base_branch || 'main'
    const autoPush = cfg.auto_push !== false
    const createPR = cfg.create_pr === true

    if (!repoPath) throw new NodeExecutionError(context.nodeId, this.type, 'Repository path is required')

    const log: string[] = []

    try {
      if (branchName) {
        try {
          await execFileAsync('git', ['checkout', '-b', branchName], { cwd: repoPath, timeout: 10000 })
          log.push(`Created branch: ${branchName}`)
        } catch {
          await execFileAsync('git', ['checkout', branchName], { cwd: repoPath, timeout: 10000 })
          log.push(`Switched to branch: ${branchName}`)
        }
      }

      await execFileAsync('git', ['add', ...files], { cwd: repoPath, timeout: 10000 })
      log.push(`Staged: ${files.join(', ')}`)

      const { stdout: statusOut } = await execFileAsync('git', ['status', '--porcelain'], { cwd: repoPath, timeout: 10000 })
      if (!statusOut.trim()) {
        return {
          commit_hash: '',
          branch_name: branchName || '',
          pr_url: '',
          success: true,
          log: 'No changes to commit'
        }
      }

      await execFileAsync('git', ['commit', '-m', commitMessage], { cwd: repoPath, timeout: 10000 })
      log.push(`Committed: ${commitMessage}`)

      const { stdout: hashOut } = await execFileAsync('git', ['rev-parse', '--short', 'HEAD'], { cwd: repoPath, timeout: 5000 })
      const commitHash = hashOut.trim()
      log.push(`Hash: ${commitHash}`)

      const { stdout: branchOut } = await execFileAsync('git', ['branch', '--show-current'], { cwd: repoPath, timeout: 5000 })
      const currentBranch = branchOut.trim()

      let prUrl = ''

      if (autoPush) {
        try {
          await execFileAsync('git', ['push', '-u', remote, currentBranch], { cwd: repoPath, timeout: 30000 })
          log.push(`Pushed to ${remote}/${currentBranch}`)
        } catch (e) {
          log.push(`Push failed: ${(e as Error).message}`)
        }
      }

      if (createPR && autoPush) {
        try {
          const { stdout: prOut } = await execFileAsync('gh', [
            'pr', 'create',
            '--base', baseBranch,
            '--head', currentBranch,
            '--title', cfg.pr_title || commitMessage,
            '--body', cfg.pr_body || `Auto-generated PR by coding agent\n\nCommit: ${commitHash}`
          ], { cwd: repoPath, timeout: 30000 })
          prUrl = prOut.trim()
          log.push(`PR created: ${prUrl}`)
        } catch (e) {
          log.push(`PR creation failed: ${(e as Error).message}`)
        }
      }

      return {
        commit_hash: commitHash,
        branch_name: currentBranch,
        pr_url: prUrl,
        success: true,
        log: log.join('\n')
      }
    } catch (error) {
      return {
        commit_hash: '',
        branch_name: '',
        pr_url: '',
        success: false,
        log: log.join('\n') + '\nError: ' + (error instanceof Error ? error.message : String(error))
      }
    }
  }
}
