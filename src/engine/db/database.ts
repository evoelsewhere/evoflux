import { SCHEMA_SQL, SCHEMA_VERSION, MIGRATIONS } from './schema'

export interface DatabaseAdapter {
  exec(sql: string): void
  prepare(sql: string): PreparedStatement
  close(): void
  pragma(key: string, value?: string): unknown
}

export interface PreparedStatement {
  run(...params: unknown[]): { changes: number }
  get(...params: unknown[]): Record<string, unknown> | undefined
  all(...params: unknown[]): Record<string, unknown>[]
}

let dbInstance: DatabaseAdapter | null = null

export function openDatabase(dbPath: string): DatabaseAdapter {
  if (dbInstance) return dbInstance

  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const db = new Database(dbPath) as DatabaseAdapter
    db.pragma('journal_mode = WAL')
    db.pragma('foreign_keys = ON')
    db.exec(SCHEMA_SQL)
    runMigrations(db)
    dbInstance = db
    console.log(`[DB] SQLite opened: ${dbPath}`)
    return db
  } catch (error) {
    console.warn('[DB] better-sqlite3 failed, using in-memory adapter:', error)
    dbInstance = createInMemoryAdapter()
    dbInstance.exec(SCHEMA_SQL)
    return dbInstance
  }
}

function runMigrations(db: DatabaseAdapter): void {
  try {
    const row = db.prepare('SELECT version FROM schema_version LIMIT 1').get()
    const currentVersion = row ? Number(row.version) : 0

    if (currentVersion < SCHEMA_VERSION) {
      for (let v = currentVersion + 1; v <= SCHEMA_VERSION; v++) {
        if (MIGRATIONS[v]) {
          db.exec(MIGRATIONS[v])
        }
      }
      if (currentVersion === 0) {
        db.prepare('INSERT INTO schema_version (version) VALUES (?)').run(SCHEMA_VERSION)
      } else {
        db.prepare('UPDATE schema_version SET version = ?').run(SCHEMA_VERSION)
      }
      console.log(`[DB] Migrated to schema version ${SCHEMA_VERSION}`)
    }
  } catch {
    db.prepare('INSERT OR IGNORE INTO schema_version (version) VALUES (?)').run(SCHEMA_VERSION)
  }
}

export function getDatabase(): DatabaseAdapter {
  if (!dbInstance) throw new Error('Database not initialized. Call openDatabase() first.')
  return dbInstance
}

export function closeDatabase(): void {
  if (dbInstance) { dbInstance.close(); dbInstance = null }
}

function bindParams(sql: string, params: unknown[]): string {
  let idx = 0
  return sql.replace(/\?/g, () => String(params[idx++] ?? null))
}

function matchWhere(whereClause: string, row: Record<string, unknown>, params: unknown[]): boolean {
  if (!whereClause) return true
  let idx = 0
  const resolved = whereClause.replace(/\?/g, () => {
    const v = params[idx++]
    return typeof v === 'string' ? `'${v}'` : String(v ?? 'null')
  })

  const conditions = resolved.split(/\s+AND\s+/i)
  for (const cond of conditions) {
    const m = cond.match(/(\w+)\s*=\s*'?(.+?)'?\s*$/)
    if (m) {
      const [, col, val] = m
      if (String(row[col]) !== val) return false
    }
  }
  return true
}

function createInMemoryAdapter(): DatabaseAdapter {
  const tables = new Map<string, Map<string, Record<string, unknown>>>()

  return {
    exec(sql: string) {
      const statements = sql.split(';').filter(s => s.trim())
      for (const stmt of statements) {
        const m = stmt.match(/CREATE TABLE IF NOT EXISTS (\w+)/i)
        if (m && !tables.has(m[1])) tables.set(m[1], new Map())
      }
    },

    prepare(sql: string) {
      return {
        run(...params: unknown[]) {
          const insertMatch = sql.match(/INSERT OR REPLACE INTO (\w+)\s*\(([^)]+)\)\s*VALUES/i)
          if (insertMatch) {
            const [, table, colsStr] = insertMatch
            const t = tables.get(table)
            if (!t) return { changes: 0 }
            const cols = colsStr.split(',').map(c => c.trim())
            const row: Record<string, unknown> = {}
            cols.forEach((col, i) => { row[col] = params[i] })
            t.set(String(row.id || row.key), row)
            return { changes: 1 }
          }

          const insertMatch2 = sql.match(/INSERT (?:OR IGNORE )?INTO (\w+)\s*\(([^)]+)\)\s*VALUES/i)
          if (insertMatch2) {
            const [, table, colsStr] = insertMatch2
            const t = tables.get(table)
            if (!t) return { changes: 0 }
            const cols = colsStr.split(',').map(c => c.trim())
            const row: Record<string, unknown> = {}
            cols.forEach((col, i) => { row[col] = params[i] })
            const key = String(row.id || row.key || '')
            if (sql.includes('OR IGNORE') && t.has(key)) return { changes: 0 }
            t.set(key, row)
            return { changes: 1 }
          }

          const updateMatch = sql.match(/UPDATE (\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$/i)
          if (updateMatch) {
            const [, table, setClause, whereClause] = updateMatch
            const t = tables.get(table)
            if (!t) return { changes: 0 }
            let setIdx = 0
            const setParts = setClause.split(',').map(s => s.trim())
            const assignments: Array<[string, unknown]> = []
            for (const part of setParts) {
              const m = part.match(/(\w+)\s*=\s*\?/)
              if (m) assignments.push([m[1], params[setIdx++]])
            }
            const whereParams = params.slice(setIdx)
            let changes = 0
            for (const [id, row] of t) {
              if (whereClause ? matchWhere(whereClause, row, whereParams) : true) {
                for (const [col, val] of assignments) row[col] = val
                t.set(id, row)
                changes++
              }
            }
            return { changes }
          }

          const deleteMatch = sql.match(/DELETE FROM (\w+)(?:\s+WHERE\s+(.+))?$/i)
          if (deleteMatch) {
            const [, table, whereClause] = deleteMatch
            const t = tables.get(table)
            if (!t) return { changes: 0 }
            const before = t.size
            if (whereClause) {
              for (const [id, row] of t) {
                if (matchWhere(whereClause, row, params)) t.delete(id)
              }
            } else {
              t.clear()
            }
            return { changes: before - t.size }
          }

          return { changes: 0 }
        },

        get(...params: unknown[]) {
          const selectMatch = sql.match(/SELECT (.+?) FROM (\w+)(?:\s+WHERE\s+(.+))?$/i)
          if (!selectMatch) return undefined
          const [, , table, whereClause] = selectMatch
          const t = tables.get(table)
          if (!t) return undefined
          for (const [, row] of t) {
            if (matchWhere(whereClause || '', row, params)) return { ...row }
          }
          return undefined
        },

        all(...params: unknown[]) {
          const selectMatch = sql.match(/SELECT (.+?) FROM (\w+)(?:\s+WHERE\s+(.+?))?(?:\s+ORDER BY\s+(.+?))?(?:\s+LIMIT\s+(\d+))?$/i)
          if (!selectMatch) return []
          const [, , table, whereClause] = selectMatch
          const t = tables.get(table)
          if (!t) return []
          const results: Record<string, unknown>[] = []
          for (const [, row] of t) {
            if (matchWhere(whereClause || '', row, params)) results.push({ ...row })
          }
          return results
        }
      }
    },

    close() {},
    pragma() { return undefined }
  }
}

export function getSchemaVersion(): number { return SCHEMA_VERSION }
