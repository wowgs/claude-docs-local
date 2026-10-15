import type { EngineInterface, Register } from 'claude-code'

// The bridge from docsync to this session's Claude Docs connector (scripts/docsynclib/bridge.py): docsync then
// needs no login of its own. When a session starts, this module starts the broker `docsync bridge`, reads the
// socket path it prints, and sets DOCSYNC_BRIDGE to it for every command and hook the session starts after. Then it
// pulls the broker's requests and calls each tool with the session's own connection ($.mcp.call). Without the
// docsync command, or when the broker stops, docsync uses Claude Code's stored login as before.
//
// The server name of the Claude Docs connector differs between the terminal (claude_ai_Claude_Docs) and the
// desktop app (a UUID). Before each `mcp__*__create` call, this module sets DOCSYNC_DOCS_SERVER to the name it
// finds, so the PreToolUse hook (`docsync hook`, matcher `^mcp__.+__create$`) knows which create tool to guard.

const PUMPS = 8 // requests served at once: docsync sends up to 8
const DOCS_TOOLS = ['batch', 'guide', 'update'] // the tools the Claude Docs connector always lists

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

export const register: Register = on => {
  on('tool.call', async ($, e, next) => {
    if (/^mcp__.+__create$/.test(e.tool)) {
      const docs = await findServer($)
      if (docs) await $.env.set('DOCSYNC_DOCS_SERVER', docs)
    }
    return next(e)
  }).catch(($, e, next) => next(e)) // the hook's own check still guards the terminal's name

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    void (async () => {
      const home = await $.env.get('HOME')
      const commands = ['docsync', ...(home ? [`${home}/.local/bin/docsync`] : [])]
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
