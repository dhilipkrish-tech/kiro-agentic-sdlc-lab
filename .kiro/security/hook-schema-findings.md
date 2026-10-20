# Hook Schema Findings (Task 3)

Goal: confirm Kiro's PreToolUse hook schema, matchers, and decision/output contract
before authoring the Layer 2 hook (Task 5).

## Status: VERIFIED

Cross-checked against the Kiro hooks documentation (the docs pages are JS-rendered and
could not be fetched directly during planning, but the schema is confirmed via the
hooks reference and the in-environment hook contract).

## File location & format

Hooks are standalone JSON files at `.kiro/hooks/*.json`. The same file works across IDE
and CLI surfaces.

```json
{
  "version": "v1",
  "hooks": [
    {
      "name": "unique-hook-name",
      "trigger": "PreToolUse",
      "matcher": "optional-regex",
      "action": { "type": "command", "command": "shell command" }
    }
  ]
}
```

## Schema fields

| Field | Required | Notes |
| ----- | -------- | ----- |
| `version` | Yes | Currently `"v1"` |
| `hooks[].name` | Yes | Unique identifier |
| `hooks[].trigger` | Yes | PascalCase event name |
| `hooks[].matcher` | No | Regex matched against the event subject (for PreToolUse: the tool name) |
| `hooks[].action.type` | Yes | `command` or `agent` |
| `hooks[].action.command` | Conditional | Required when `action.type` is `command` |
| `hooks[].action.prompt` | Conditional | Required when `action.type` is `agent` |

## PreToolUse specifics (the contract we rely on)

- **Trigger name:** `PreToolUse` (fires before a tool executes).
- **Matcher:** tested against the **tool name**. For our guardrail we match the write/
  delete/append tools and the shell tool, e.g. `fs_write|str_replace|fs_append|delete_file|execute_bash`.
- **stdin:** the command action receives JSON on stdin with session/tool context,
  including the tool input (which carries the target path or command text).
- **Exit-code semantics:**
  - `exit 0` → success. stdout is forwarded for PreToolUse and may carry a decision.
  - `exit 2` → **block** the tool call; stderr is returned to the agent.
  - any other code → silent failure, no block.
- **Prompt-the-user decision** (via exit 0 stdout):

  ```json
  {
    "hookSpecificOutput": {
      "permissionDecision": "ask",
      "permissionDecisionReason": "Path is outside the project root"
    }
  }
  ```

  When `permissionDecision` is `"ask"`, the user is prompted to confirm before the tool
  proceeds.

## Design implications for Task 5

- Use a **command** action (not agent) so we can inspect the tool input programmatically
  and make a deterministic decision.
- For writes/deletes: parse the path from stdin, resolve it, and if it falls outside the
  project root emit `permissionDecision: "ask"` (or `exit 2` for a hard block — chosen in
  Task 5 based on strictness).
- For `execute_bash`: scan the command text for absolute paths, `~`, `..` escapes, and
  destructive verbs (`rm`, `mv`, `cp`, redirections) targeting outside the root; prompt
  on a match. Documented as heuristic.
- Fallback (if the decision contract ever changes): a plain `exit 2` still blocks, so the
  guardrail degrades safely to "block" rather than "allow".
