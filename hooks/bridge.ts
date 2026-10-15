import type { EngineInterface, Register } from 'claude-code'

// The bridge from docsync to this session's Claude Docs connector (scripts/docsynclib/bridge.py): docsync then
// needs no login of its own. When a session starts, this module starts the broker `docsync bridge`, reads the
// socket path it prints, and sets DOCSYNC_BRIDGE to it for every command and hook the session starts after. Then it
// pulls the broker's requests and calls each tool with the session's own connection ($.mcp.call). Without the
// docsync command, or when the broker stops, docsync uses Claude Code's stored login as before.
//
// The guard on the Docs tools that write: in a docs-local project Claude may only write comments through them
// (`docsync hook` decides, scripts/docsynclib/claude.py). It sits here, in `tool.call`, and not in a PreToolUse
// hook: `tool.call` sees Claude's calls but not this module's own $.mcp.call, while a PreToolUse hook sees both and
// would refuse docsync's writes through the bridge. The Claude Docs server is claude_ai_Claude_Docs in the terminal
// and a UUID in the desktop app; the guard passes the name it finds on as DOCSYNC_DOCS_SERVER.

const PUMPS = 8 // requests served at once: docsync sends up to 8
const DOCS_TOOLS = ['batch', 'guide', 'update'] // the tools the Claude Docs connector always lists
const WRITES = /^mcp__.+__(create|batch|update|delete)$/ // the tool names the guard asks docsync about
const RESERVED = new Set(['tool', 'tool_use_id', 'consent', 'agentId', 'requestMeta']) // tool.call's own keys

let server: string | undefined // the Claude Docs server's name in this session, once found

const findServer = async ($: EngineInterface): Promise<string | undefined> => {
  if (server) return server
  const tools = new Map<string, Set<string>>()
  for (const t of await $.tool.list()) {
    const m = /^mcp__(.+)__([^_]+)$/.exec(t.name)
    if (!t.mcp || !m) continue
    if (m[2] === 'guide' && !/Docs/.test(t.description)) continue
    const names = tools.get(m[1]) ?? new Set<string>()
    names.add(m[2])
    tools.set(m[1], names)
  }
  for (const [name, names] of tools) if (DOCS_TOOLS.every(t => names.has(t))) server = name
  return server
}

// `docsync hook` on one call, as a PreToolUse hook would get it: the reason of its deny, or undefined
const guard = async ($: EngineInterface, call: Record<string, unknown>): Promise<string | undefined> => {
  const docs = await findServer($)
  const toolInput = Object.fromEntries(Object.entries(call).filter(([k]) => !RESERVED.has(k)))
  const stdin = JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: call.tool, tool_input: toolInput })
  for (const python of ['python3', 'python']) {
    let ran
    try {
      ran = await $.process.run([python, `${$.plugin.root}/scripts/docsync.py`, 'hook'], {
        stdin,
        env: docs ? { DOCSYNC_DOCS_SERVER: docs } : {},
      })
    } catch {
      continue // this interpreter did not start: try the next one
    }
    if (ran.exitCode !== 0) throw new Error(`docsync hook exited with ${ran.exitCode}: ${ran.stderr.slice(0, 300)}`)
    if (!ran.stdout.trim()) return undefined
    const answer = JSON.parse(ran.stdout) as { hookSpecificOutput?: { permissionDecisionReason?: string } }
    return answer.hookSpecificOutput?.permissionDecisionReason ?? 'docs-local: refused'
  }
  throw new Error('no python3 or python to run docsync hook')
}

export const register: Register = on => {
  on('tool.call', async ($, e, next) => {
    if (!WRITES.test(e.tool)) return next(e)
    const reason = await guard($, e)
    return reason ? { deny: reason } : next(e)
  }).catch(async ($, e, next) => {
    if (next.called) return next(e)
    const docs = await findServer($).catch(() => undefined)
    // fail closed for the Claude Docs tools only: another server's tools go on
    if (docs && !e.tool.startsWith(`mcp__${docs}__`) && !e.tool.startsWith('mcp__claude_ai_Claude_Docs__')) return next(e)
    return { deny: 'docs-local: the guard on the Docs tools failed' }
  })

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    void (async () => {
      const home = await $.env.get('HOME')
      const commands = [`${$.plugin.root}/bin/docsync`, 'docsync', ...(home ? [`${home}/.local/bin/docsync`] : [])]
      for (const command of commands) {
        let socketPath: string | undefined
        const ask = (path: string, body?: unknown) =>
          $.http.fetch(`http://bridge${path}`, {
            method: body === undefined ? 'GET' : 'POST',
            socketPath,
            headers: { 'Content-Type': 'application/json' },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          })
        const pump = async () => {
          for (;;) {
            const r = await ask('/next')
            if (r.status !== 200) continue
            const job = JSON.parse(r.text) as { id: string; tool: string; args: Record<string, unknown> }
            const docs = await findServer($)
            if (!docs) {
              await ask(`/result/${job.id}`, { unavailable: 'no Claude Docs connector in this session' })
              continue
            }
            let out: unknown
            try {
              out = { result: await $.mcp.call(docs, job.tool, job.args) }
            } catch (err) {
              out = { error: String(err) }
            }
            await ask(`/result/${job.id}`, out)
          }
        }
        try {
          const broker = $.process.spawn({ argv: [command, 'bridge'] })
          for await (const { stream, text } of broker) {
            if (socketPath || stream !== 'stdout') continue
            const m = /listening (\S+)/.exec(text)
            if (!m) continue
            socketPath = m[1]
            await $.env.set('DOCSYNC_BRIDGE', socketPath)
            for (let i = 0; i < PUMPS; i++) void pump().catch(() => undefined)
          }
        } catch {
          // this command could not start: try the next one
        }
        if (socketPath) {
          await $.env.set('DOCSYNC_BRIDGE', undefined) // the broker ended: docsync uses its own login again
          return
        }
      }
    })()
    return started
  })
}
