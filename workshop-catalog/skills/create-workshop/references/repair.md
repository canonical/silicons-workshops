# Repair rules

Read this before the first `diagnose` or `stop` verdict from
`scripts/run_stages.py`.

## Contents

- Scope: what may and may not change
- The loop
- Diagnosing an unknown failure
- Writing the note
- Escalation report
- Adding a known fix
- Gotchas

## Scope: what may and may not change

The goal is a working build environment, never a changed kernel.

| May change (tooling) | Never change |
|---|---|
| `.workshop/**`: the definition, hooks, SDK definitions | `kernel-src/**`: the kernel tree |
| `sdk/**`: build scripts, `snapcraft.yaml` | patches, overlays, out-of-tree drivers |
| `.gitignore` | `config/workshop.yaml`, including the kernel repository, ref and flavour |
| apt packages in the `EXTRA_PACKAGES` list of `setup-base` | `catalog.yaml`, other workshops, the bundled template |

`apply-fix` and `record-fix` enforce this: a change outside the left column is
reverted and refused, and the kernel tree is compared before and after.

Decide by what the fix touches, not by what the error looks like:

- A missing compiler, tool or library on the build host: tooling. Add the
  package to `EXTRA_PACKAGES`.
- A script flag, path or `snapcraft.yaml` shape: tooling.
- A C compile error under `drivers/`, `arch/`, `fs/`, `kernel/`...: kernel. Stop.
- A `check-config` or annotations mismatch (`CONFIG_X changed from y to -`):
  kernel. Stop and report it, even though a one-line `sed` on the annotations
  file would hide it.
- A patch that does not apply, or a ref that does not exist: kernel/config. Stop.
- The wrong kernel for the board: not a failure; the user chose the target.

If the only way to make the build pass is to change the kernel, the config or
the ref, the answer is a `stop` with a clear report.

## The loop

```text
run  ->  ok?  -> done
          |
          no -> verdict
                 fix-available -> apply-fix -> run
                 diagnose      -> edit tooling -> record-fix -> run
                 wait          -> wait -> run
                 stop          -> report
```

- `attempts_used` counts repair iterations (each `apply-fix` or `record-fix`).
  The limit is 5. After the fifth repair the next failure is a `stop`.
- Environment and kernel failures cost nothing: they stop at once.
- The same signature after a repair stops the loop: the repair did not work, and
  trying a fifth variation of it is not progress.
- A repair is tested before the next one is made: `run` must happen between two
  repairs.
- A fix that changes no file (`fix-noop`) means the workshop already had it, so
  the cause is elsewhere (usually the network). Stop.

## Diagnosing an unknown failure

1. Read the `log_tail` in the verdict, then the log file for the first error,
   not the last line: build output often ends with a summary of an earlier
   failure.
2. Name the cause in one sentence and check it against the scope table.
3. Check what the kernel itself asks for: `kernel-src/debian/control`
   `Build-Depends`, and `references/toolchain-notes.md`.
4. Make the smallest edit in `.workshop/` or `sdk/`. Prefer restoring a file
   from `assets/workshop-template/` over rewriting it by hand.
5. If the fix changes a `.workshop/` file, `record-fix` restarts from `launch`,
   which runs `workshop refresh`. A change in `sdk/` needs no relaunch: the
   project directory is mounted into the workshop.
6. Run `record-fix --note "<cause and change>"`, then `run`.

## Writing the note

One line each: the symptom, the cause, the change. It goes into
`REPAIR-LOG.md`, which the user reads, so name files and packages.

> `kernel-build-debs` stopped with `dwarfdump: not found`. The jammy 5.15 tree
> needs the `dwarfdump` package (separate from `dwarves`). Added it to
> `EXTRA_PACKAGES` in `.workshop/jammy-build/hooks/setup-base`.

## Escalation report

When the verdict is `stop`, write `HANDOFF.md` with:

- **Stage and class**: for example `snap`, `kernel-or-patch`.
- **Evidence**: the log path and the 5-10 lines that show the cause.
- **What was tried**: each repair from `REPAIR-LOG.md`, and its result.
- **What is needed**: for environment, retry when the network or disk is back;
  for kernel, a question for the kernel team (quote the error); for budget or
  repeated failure, the open hypothesis.
- **What works**: stages that passed, and any artifact already built.

Do not retry after a `stop`. Do not describe the workshop as working.

## Adding a known fix

When a failure recurs and the fix is mechanical:

1. Reproduce it and take the smallest regex that only the real cause produces.
2. Add an entry to `references/known-fixes.json` (fields are described at its
   top). Prefer `restore-from-template` or `fix-snapcraft` over new edit logic.
3. If the fault is in the template, fix `assets/workshop-template/` as well, and
   add a check to `scripts/check_workshop.py`, so new workshops never have it.
4. Add a case to `tests/test_create_workshop.py`.

## Gotchas

- `workshop` commands need the workshop directory as the current directory or
  `-p <dir>`; `run_stages.py` handles this.
- Cancelling a `workshop launch` client does not stop the launch in the daemon.
  Relaunching then says the workshop exists. Wait for the change to finish
  (`workshop changes`); the `wait` verdict covers it.
- `snapcraft pack` leaves `parts/`, `stage/`, `prime/` owned by the container's
  root mapping inside `sdk/snap/snapcraft/`. They are gitignored; to remove
  them use `sudo rm -rf`.
- A shallow tag clone is enough for the builds: they only use the checked-out
  tree and `git rev-parse HEAD`.
- Both builds compile the kernel, so `deb` plus `snap` is about two hours.
- The `.deb` and snap builds are validated separately in
  `references/kernel-sources.json`; a passing `.deb` build says nothing about
  the snap.
