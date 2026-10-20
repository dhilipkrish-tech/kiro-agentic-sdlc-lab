# Security Controls

Controls that prevent or surface any agent action touching files **outside** the project
root `/Users/dhilipkrish/Desktop/kiro-agentic-sdlc-lab`. Built threat-model-first, with
deny-by-default as the organizing principle.

Start with the [threat model](./threat-model.md). Every control below traces back to a
threat (T1–T4) there.

> **History:** this project originally shipped a custom Docker sandbox + a PreToolUse
> boundary-guard hook. Those were **retired** once Kiro shipped native **Local
> Sandboxing**, which does the same job better — at the OS kernel, per command, with no
> container to launch. See "Retired controls" at the end.

## Defense in depth (order of defense)

| Layer | Control | Where | Primary / Deterrent | Threats |
| ----- | ------- | ----- | ------------------- | ------- |
| 0 | **Kiro Local Sandboxing** — kernel-enforced (seatbelt on macOS). Writes confined to the project dir + temp; credential paths (`~/.ssh`, `~/.aws`) denied; network via a filtering proxy | `../settings/sandbox.json` | **Primary** | T1, T2, T3 |
| 1 | Steering policy — announce+confirm outside actions; treat external output as untrusted | `../steering/security-guardrails.md` | Behavioral | T1, T2 |
| 2 | Audit monitor hook — alerts after each turn on new outside-access entries | `../hooks/audit-monitor.json`, `tests/monitor-audit.sh` | Visibility | T3, T4 |
| 3 | Control tests — prove the sandbox + injection resistance still hold | `tests/control-tests.sh` | Assurance | all |

```
UNTRUSTED (web, external files, host fs)
        |
        v
  [Layer 0 Local Sandboxing] <- kernel denies writes/credential reads outside project
        |
  [Layer 1 steering]         -> announce + confirm, treat external output as data
        |
  [Layer 2 audit monitor]    -> alert on any logged outside-access attempt
        |
  [Layer 3 control tests]    -> continuously prove the above still holds
```

## Primary control: Kiro Local Sandboxing (Layer 0)

Enabled for this project via `.kiro/settings/sandbox.json`:

```json
{ "enabled": true }
```

When active, the OS kernel (seatbelt on macOS) enforces — regardless of how a command is
phrased, including a script written to do the reading:

- **Writes** confined to the project directory + temp space.
- **Reads** of common credential paths (`~/.ssh`, `~/.aws`) denied.
- **Network** forced through a local proxy that filters by domain.

The IDE status bar shows **"Command sandbox: Active"** when it is on. Policy can be shaped
further in `permissions.yaml` (same policy file that governs tool authorization). Scope:
this file is project-only; a global default lives at `~/.kiro/settings/sandbox.json`.

Requires Kiro IDE 1.3+ / CLI 2.31+ (local V3 sessions). Reference:
<https://kiro.dev/blog/local-sandboxing/>.

## Running the control tests (Layer 3)

```bash
bash .kiro/security/tests/control-tests.sh   # verifies the live sandbox + injection resistance
bash .kiro/security/tests/monitor-audit.sh   # alerts on new outside-access entries
```

The audit monitor is also wired to run automatically after each agent turn via the
`audit-monitor` Stop hook.

## Verification status (honest)

- **Local Sandboxing verified live** (Kiro 1.3.0, seatbelt on Apple Silicon macOS). A
  shell command writing to `~/sandbox_probe.txt` was refused with "operation not
  permitted", and listing `~/.ssh` was blocked — both enforced by the OS kernel, not a
  Kiro prompt.
- **Steering + audit monitor** verified: the monitor correctly alerts on new log entries
  and stays quiet otherwise.
- **Injection fixture** retained to confirm the agent treats embedded instructions as
  data (Layer 1 behavioral check).

## Residual risk

- Local Sandboxing restricts **commands the agent runs**, not the agent process itself
  (by design — so it can be toggled mid-session and machine credentials never enter it).
- **Network** is filtered, not fully severed; approved domains are reachable.
- Steering (Layer 1) is behavioral and model-dependent; never the sole line of defense.
- For hard data-residency isolation, Kiro's cloud sandbox or a dedicated VM goes further.

## Retired controls (kept for history)

Removed once Local Sandboxing landed, to avoid double-maintenance:

- **Custom Docker sandbox** (`isolation/Dockerfile`, `isolation/run-agent.sh`) — replaced
  by kernel-level, per-command enforcement with no container to build or launch.
- **PreToolUse boundary-guard hook** (`hooks/boundary-guard.json` + its scripts) — the
  kernel now denies outside writes and credential reads directly, so the heuristic
  shell-command inspection is no longer needed. The `hook-schema-findings.md` note is
  retained as a record of the verified hook contract.
