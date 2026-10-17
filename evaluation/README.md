# Evaluation harness

Automated evaluation of **one** Kiro turn: the requirement-change turn that moved
the maximum claim quantity from 30 to 60. The turn is selected by its
`executionId` (`21c6ee19-82a7-44f6-9f97-6554b9f4b46f`) and its
`turn_start`/`turn_end` events — so the earlier/later turns (the initial test
run, the "need frontend passes" turn, the Kiro-capability investigation, and this
harness turn) are **not** evaluated.

## Full evaluation — ONE command

```bash
python3 evaluation/run_full_eval.py
```

This single command, run from a normal macOS Terminal:

1. allocates **free ephemeral ports** for backend + frontend (never reuses your
   dev servers on 8000/5173, never adopts an already-listening server),
2. starts a fresh backend and waits for a real `GET /api/health` 200,
3. starts a fresh frontend with `VITE_API_BASE` pointed at that backend and waits
   until it actually serves,
4. verifies frontend→backend connectivity and that CORS returns an
   `Access-Control-Allow-Origin` header (verification only; the app's CORS config
   is not modified),
5. runs the backend/application adjudication matrix,
6. runs the existing **3 Playwright UI tests** against the fresh frontend,
7. evaluates the recorded Kiro requirement-change turn (same checks as below),
8. writes ONE combined report (`evaluation/out/evaluation.json` + `.html`) with
   **two independent verdicts** — even if a stage fails,
9. the process exit code reflects **current application health only** (see below),
10. always terminates **only** the backend/frontend processes it started — on
    success, on failure, and on Ctrl-C (process-group kill + `atexit`/signal
    handlers).

UI PASS requires BOTH the real `npx playwright test` exit code `0` AND structured
JSON evidence that all 3 specs passed. If the browser cannot launch, UI is
reported `BLOCKED` with the real failure evidence — never PASS.

### Two independent verdicts (no combined "overall")

The report deliberately does **not** collapse current and historical results into
one verdict. They answer different questions and are reported separately:

- **`currentApplicationValidation`** — is the app healthy *now*? Aggregates the
  fresh-backend adjudication matrix, the FE→BE connectivity + CORS check, and the
  live Playwright UI rerun.
- **`historicalKiroExecution`** — what did the *original recorded agent run*
  actually achieve? Aggregates the recorded-evidence checks. This is never forced
  to PASS; the original Playwright browser-launch BLOCK is preserved.

A historical BLOCKED does not hide a current failure, and a current PASS does not
erase the historical failure. Both are always visible.

### Exit codes (full run)

By default, the **process exit code reflects current application validation
only** — so CI/demo gating tracks whether the app works today:

| Exit | Meaning |
| ---- | ------- |
| `0` | current application validation PASS |
| `2` / `3` / `4` | current validation worst verdict FAIL / BLOCKED / UNKNOWN |

The historical verdict is printed and stored in the report but does **not** move
this exit code. To gate on history instead, run:

```bash
python3 evaluation/run_full_eval.py --historical-gate
```

which makes the exit code reflect the historical verdict (nonzero for
FAIL/BLOCKED/UNKNOWN). The report content is identical either way; only the exit
code changes.

## Turn-only evaluation (still available)

```bash
python3 evaluation/evaluate.py
```

Outputs the same two report files, but runs only the session-log checks plus a
self-spawned backend matrix (no frontend / Playwright).

Optional: `--skip-app-recheck` (session-log checks only, no backend spawned),
`--session-log <path>` (point at an explicit `messages.jsonl`).

### Exit codes

Every application check and every Kiro execution check is **required**. The
command exits nonzero if any required check is not `PASS`:

| Exit | Meaning |
| ---- | ------- |
| `0` | all required checks `PASS` |
| `2` | at least one `FAIL` present (worst severity) |
| `3` | at least one `BLOCKED` (and no `FAIL`) |
| `4` | at least one `UNKNOWN` (and no `FAIL`/`BLOCKED`) |

`UNKNOWN` (missing/ambiguous evidence) is a non-pass outcome by design, so it
also fails the run.

## What it reads / does not touch

- Reads **only** the active session's `messages.jsonl` (read-only).
- Does **not** modify Kiro settings, application code, existing tests, or any
  unrelated change. It only writes its two reports under `evaluation/out/`.
- Reports contain distilled evidence excerpts, never raw session payloads.

## Verdicts

`PASS` · `FAIL` · `BLOCKED` · `UNKNOWN`. Missing evidence is never `PASS`.
Results are split into two clearly separated groups.

### Application checks — *independently rerun*

Spawns a fresh `uvicorn` backend from this checkout on a dedicated port
(`127.0.0.1:8137`), waits for `/api/health`, posts each claim, then tears the
process down (even on error):

| Check | Expected |
| ----- | -------- |
| Normal drug, qty 31 | `200 PAID` |
| Normal drug, qty 60 | `200 PAID` |
| Normal drug, qty 61 | `200 REJECTED / QUANTITY_LIMIT_EXCEEDED` |
| PA drug, qty 60 | `200 REJECTED / PRIOR_AUTHORIZATION_REQUIRED` |
| PA drug, qty 61 | `200 REJECTED / QUANTITY_LIMIT_EXCEEDED` |
| qty 0 | `HTTP 422` |

If the backend can't be spawned/health-checked, these are `BLOCKED`, not `FAIL`.

### Kiro execution checks — *recorded in the session log*

1. **File-edit actions** — lists every `fs_write`/`str_replace`/`fs_append`/
   `delete_file` with target path and recorded success.
2. **Test commands** — lists recorded `pytest`/`playwright` commands with their
   recorded `success` flag and a short result excerpt.
3. **Edits outside allowed files** — compares edited paths to the task's allowed
   set; any file outside it is `FAIL`; unresolved paths are `UNKNOWN`.
4. **Failed actions & repeated commands** — reports `tool.success == false`
   calls and exact repeated shell commands. Repeats are **reported, not assumed**
   to be defects.
5. **Turn duration** — from `turn_start`→`turn_end`, cross-noted against the
   recorded `usage_summary.elapsedTime`.
6. **Completion report vs. evidence** — checks the report's **explicit**
   test-count/status claims (e.g. "20 passed, 0 failed"; Playwright "blocked")
   against recorded results. Vague/ambiguous claims are `UNKNOWN`.

## Allowed files for the task

`backend/app/models.py`, `backend/tests/test_rules.py`,
`backend/tests/test_api.py`, `tests-e2e/claim.spec.js`, the three spec files
under `.kiro/specs/pharmacy-claim-validation/`, and `README.md` (the quantity
limit was documented there and updated as part of the change).

## Files

| File | Role |
| ---- | ---- |
| `evaluate.py` | entry point; orchestrates + renders |
| `config.py` | declarative config: target turn, allowed files, app-check matrix, port |
| `session_reader.py` | read-only session-log parser, scoped to the target turn |
| `kiro_checks.py` | the six recorded-evidence checks |
| `app_recheck.py` | fresh-backend spawn + HTTP matrix + cleanup |
| `report.py` | JSON + HTML rendering |
