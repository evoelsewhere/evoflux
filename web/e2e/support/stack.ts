import { type ChildProcess, spawn, spawnSync } from 'node:child_process'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import net from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

// One isolated stack: mock provider + `evoflux-server serve` (Python behind it)
// + a Vite preview of the production build proxying /api to the gateway (the dev
// server's on-demand dependency optimisation reloads the page in a loop). Everything lives in a temp directory
// and no real provider key is involved.

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const webRoot = path.join(repoRoot, 'web')

function required(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is not set; run the suite with scripts/migration/e2e.sh`)
  return value
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = net.createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address() as net.AddressInfo
      probe.close(() => resolve(port))
    })
  })
}

async function waitFor<T>(what: string, probe: () => Promise<T | undefined>, timeoutMs: number): Promise<T> {
  if (process.env.EVOFLUX_E2E_DEBUG) console.log(`[stack] ${new Date().toISOString()} waiting for ${what}`)
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const value = await probe()
      if (value !== undefined) return value
    } catch {
      // not ready yet
    }
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`)
    await sleep(250)
  }
}

function killTree(pid: number): void {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'])
  } else {
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      // already gone
    }
  }
}

function pump(child: ChildProcess, log: string[], onLine?: (line: string) => void): void {
  let pending = ''
  const feed = (chunk: Buffer) => {
    pending += chunk.toString('utf8')
    const lines = pending.split(/\r?\n/)
    pending = lines.pop() ?? ''
    for (const line of lines) {
      log.push(line)
      if (log.length > 200) log.shift()
      onLine?.(line)
    }
  }
  child.stdout?.on('data', feed)
  child.stderr?.on('data', feed)
}

export interface Stack {
  /** The Vite URL the browser opens. */
  webUrl: string
  /** The gateway URL (what Vite proxies /api to). */
  apiUrl: string
  /** Pid of the Python child the gateway supervises. */
  pythonPid(): number
  /** Kill the Python child (and its launcher tree); the gateway restarts it. */
  killPython(): void
  tail(): string
  stop(): Promise<void>
}

export interface StackOptions {
  routeOverride?: string
  /** A copy of a real config dir (provider keys included): used instead of the mock provider. Never logged. */
  realConfigDir?: string
}

export async function startStack(options: StackOptions = {}): Promise<Stack> {
  const server = required('EVOFLUX_E2E_SERVER_BIN')
  const pythonBin = required('EVOFLUX_E2E_PYTHON_BIN')
  const root = mkdtempSync(path.join(tmpdir(), 'evoflux-e2e-'))
  const log: string[] = []
  const pids: number[] = []

  const stop = async () => {
    for (const pid of [...pids].reverse()) killTree(pid)
    await sleep(500)
    for (let attempt = 0; attempt < 10; attempt++) {
      try {
        rmSync(root, { recursive: true, force: true })
        return
      } catch {
        await sleep(500)
      }
    }
  }

  try {
    const mock = spawn(pythonBin, [path.join(repoRoot, 'scripts', 'migration', 'e2e_mock_provider.py')], {
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    pids.push(mock.pid!)
    let providerUrl = ''
    pump(mock, log, (line) => {
      if (line.startsWith('MOCK_PROVIDER ')) providerUrl = line.slice('MOCK_PROVIDER '.length).trim()
    })
    await waitFor('the mock provider', async () => providerUrl || undefined, 30_000)

    const [data, config, state, cache, workspace, wiki, home] = ['data', 'config', 'state', 'cache', 'workspace', 'wiki', 'home'].map(
      (name) => {
        const dir = path.join(root, name)
        mkdirSync(dir, { recursive: true })
        return dir
      },
    )
    if (options.realConfigDir) cpSync(options.realConfigDir, config, { recursive: true })
    const stateFile = path.join(state, 'python-child.json')
    const apiPort = await freePort()
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
      APPDATA: path.join(home, 'AppData', 'Roaming'),
      LOCALAPPDATA: path.join(home, 'AppData', 'Local'),
      EVOFLUX_APP_ENV: 'development',
      EVOFLUX_DATA_DIR: data,
      EVOFLUX_CONFIG_DIR: config,
      EVOFLUX_STATE_DIR: state,
      EVOFLUX_CACHE_DIR: cache,
      EVOFLUX_WORKSPACE_DIR: workspace,
      EVOFLUX_WIKI_DIR: wiki,
      EVOFLUX_MODEL_REGISTRY_REFRESH: 'false',
      EVOFLUX_GATEWAY_PYTHON_BIN: pythonBin,
      EVOFLUX_GATEWAY_SITE_PACKAGES: repoRoot,
      EVOFLUX_GATEWAY_CLI_ENTRY: path.join(repoRoot, 'app', 'cli', '__main__.py'),
      EVOFLUX_GATEWAY_STATE_FILE: stateFile,
      // Also in the environment so a restarted Python child still reaches the mock.
      ROUTER9_BASE_URL: `${providerUrl}/v1`,
      ROUTER9_API_KEY: 'mock-key',
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    }
    delete env.EVOFLUX_ROUTE_OVERRIDE
    if (options.routeOverride) env.EVOFLUX_ROUTE_OVERRIDE = options.routeOverride

    const gateway = spawn(server, ['serve', '--host', '127.0.0.1', '--port', String(apiPort)], {
      cwd: root,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    pids.push(gateway.pid!)
    pump(gateway, log)
    const apiUrl = `http://127.0.0.1:${apiPort}`
    await waitFor(
      'the gateway to serve /api/health/live',
      async () => ((await fetch(`${apiUrl}/api/health/live`)).ok ? true : undefined),
      120_000,
    )

    // Register the mock provider the way the UI's settings do, then seed agents.
    if (!options.realConfigDir) {
      const put = await fetch(`${apiUrl}/api/settings/providers/router9`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ api_key: 'mock-key', extra: { ROUTER9_BASE_URL: `${providerUrl}/v1` } }),
      })
      if (!put.ok) throw new Error(`provider setup failed: ${put.status} ${await put.text()}`)
      const seed = await fetch(`${apiUrl}/api/settings/seed`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ provider_model: 'router9:mock-model' }),
      })
      if (!seed.ok) throw new Error(`seed failed: ${seed.status} ${await seed.text()}`)

    }

    const webPort = await freePort()
    const vite = spawn(
      process.execPath,
      [path.join(webRoot, 'node_modules', 'vite', 'bin', 'vite.js'), 'preview', '--outDir', required('EVOFLUX_E2E_WEB_DIST'), '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'],
      { cwd: webRoot, env: { ...env, VITE_API_PROXY_TARGET: apiUrl }, stdio: ['ignore', 'pipe', 'pipe'] },
    )
    pids.push(vite.pid!)
    pump(vite, log)
    const webUrl = `http://127.0.0.1:${webPort}`
    await waitFor('Vite', async () => ((await fetch(webUrl)).ok ? true : undefined), 60_000)

    const pythonPid = () => (JSON.parse(readFileSync(stateFile, 'utf8')) as { pid: number }).pid
    return {
      webUrl,
      apiUrl,
      pythonPid,
      killPython: () => killTree(pythonPid()),
      tail: () => log.join('\n'),
      stop,
    }
  } catch (error) {
    const tail = log.join('\n')
    await stop()
    throw new Error(`${(error as Error).message}\n--- stack log tail ---\n${tail}`)
  }
}
