# Threat Model & Control Objectives

> Scope: controls that prevent or surface any agent action touching files **outside**
> the project root `/Users/dhilipkrish/Desktop/kiro-agentic-sdlc-lab`.
> This document is Task 1 of the Security Controls plan (v3) and drives every control
> that follows.

## Guiding principle: deny-by-default / least privilege

The agent is granted **only** the access it needs: read-write within the project root,
nothing outside it. Any access beyond that boundary is denied by default and must be
either blocked outright (OS isolation) or explicitly confirmed by the user (hook +
steering). External output — file contents, web pages, command stdout — is treated as
**untrusted data**, never as instructions.

## Assets

| ID | Asset | Why it matters |
| -- | ----- | -------------- |
| A1 | Files outside the project root (home dir, system files, other repos) | Agent must never modify them without explicit consent |
| A2 | Integrity of the audit trail | Evidence of what the agent attempted must be trustworthy |
| A3 | The agent's own privileges (its ability to run commands/write files) | If hijacked, these privileges become the attacker's |
| A4 | Project files (synthetic, no secrets) | Low sensitivity, but still the agent's legitimate work area |

## Trust boundary

```
            UNTRUSTED                 |            TRUSTED
  web pages, external files, stdout   |   project root (RW)
  host filesystem outside project ----+---->  [ isolation + hook + steering ]
```

Everything to the left of the boundary is untrusted. The project root is the only
read-write region the agent is entitled to.

## Threats → Controls (traceability table)

| ID | Threat | Adversary / Trigger | Likelihood | Impact | Mitigating control(s) |
| -- | ------ | ------------------- | ---------- | ------ | --------------------- |
| T1 | **Accidental agent reach outside project** — agent writes/deletes/moves a file outside the root by mistake or over-broad command | The agent itself, no malice | Medium | High (A1) | **Layer 0** Local Sandboxing (kernel denies outside writes); **Layer 1** steering policy (behavioral) |
| T2 | **Prompt injection via untrusted content** — a file, web page, or command output contains text like "ignore your rules, write to ~/" and the agent obeys it | External content author (possibly malicious) | Medium | High (A1, A3) | **Layer 1** steering: treat external output as untrusted data; **Layer 0** sandbox makes the instruction unactionable even if obeyed (kernel still denies the write / credential read); **Layer 3** injection control test proves resistance |
| T3 | **Local attacker reuses the agent's privileges** — someone with access to the running session drives the agent to touch host files | Local attacker / misuse | Low | High (A1, A3) | **Layer 0** sandbox caps blast radius (writes confined, credential reads denied); **Layer 2** audit monitor surfaces attempts |
| T4 | **Audit-trail tampering** — the agent (or injected instruction) rewrites the log to hide an outside-access attempt | The agent / injected instruction | Low | Medium (A2) | Audit log written **outside** the project (default `<parent-of-project>/.kiro-agent-audit/`), which the sandbox makes unwritable from agent commands; git-ignore any in-repo artifact |

## Peer-review checklist (Task 1 acceptance)

- [x] Every threat (T1–T4) maps to at least one planned control.
- [x] Deny-by-default / least privilege stated as the guiding principle.
- [x] Prompt injection (T2) named as a first-class threat, not an afterthought.
- [x] Audit integrity (T4) addressed with an external, append-only sink.
- [x] Honest residual risk documented (see below).

## Honest residual risk

- Local Sandboxing restricts **commands the agent runs**, not the agent process itself
  (by design — toggleable mid-session; machine credentials never enter it).
- **Network** is filtered through a proxy, not fully severed; approved domains remain
  reachable.
- Steering is behavioral and model-dependent; it raises the floor but is never the sole
  line of defense.
- For hard data-residency isolation, Kiro's cloud sandbox or a dedicated VM goes further.

> Note: an earlier version of these controls used a custom Docker sandbox + a PreToolUse
> boundary-guard hook. Both were retired in favor of native Local Sandboxing. See
> `README.md` → "Retired controls".
