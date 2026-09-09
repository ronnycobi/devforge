# DevForge repo tooling (Claude Code / Cursor)

These make working *on this repo* with an AI assistant reliable. They are features of
the **AI tool**, not of the DevForge app. (For DevForge offering these to its own
customers, see `docs/TOOLING_CAPABILITIES.md`.)

## Skills — reusable playbooks
`.claude/skills/devforge-feature/SKILL.md` captures this project's build loop
(inspect → implement → migrate → test app then full suite → verify workspaces clean →
commit/push with the right trailer). The assistant loads it when you work on a
feature, so the conventions don't have to be re-explained.

Add a skill: create `.claude/skills/<name>/SKILL.md` with YAML frontmatter (`name`,
`description`) followed by the instructions.

## Hooks — automatic guardrails
`.claude/settings.json` registers a **PostToolUse** hook
(`.claude/hooks/post_commit_reminder.sh`) that runs after every Bash call and, when
the command was a `git commit`, warns if a model change looks like it's missing a
migration and reminds you to push. It is advisory only — it always exits 0 and never
blocks. Extend it with more checks, or add other events (PreToolUse, Stop, etc.).

## MCP — connect the assistant to external tools/data
MCP servers let the assistant reach GitHub, a database, a browser, etc. This machine
has `node` but not `npx` on PATH, so nothing is wired by default (a broken server
would fail silently — we don't ship that). To add one, create `.mcp.json` in the repo
root, e.g.:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  }
}
```

Ensure `npx` is installed and on PATH first, then restart the assistant so it picks up
the server. Servers needing credentials should read them from the environment, never
be committed.
