# autostart — make the bot a launchable executable that starts on boot

## Goal

Today the bot is started by hand: `cd` into the repo, activate `venv`, run
`python leaps_spy.py`. After a reboot nothing runs. Deliver:

1. **An executable launcher**, `run.sh`, at the repo root, that works from any
   current directory (double-click, `~/…/run.sh`, or systemd).
2. **Start on boot** via a systemd *user* unit that runs the launcher,
   restarts it if it dies, and logs to the journal.

## Project rules / facts this task touches

There is no project `CLAUDE.md`/`AGENTS.md`. Facts from the code that constrain
the design:

- `leaps_spy.py` resolves everything **relative to the current working
  directory**: `load_dotenv()` finds `.env` in cwd, `STATE_FILE =
  "leaps_state.json"` is relative, and `get_git_commit()` runs `git rev-parse`
  in cwd. The launcher and the unit **must** run it with cwd = repo root. Do not
  change `leaps_spy.py` in this task.
- Dependencies live in `venv/` (python at `venv/bin/python`, 3.14). Use it
  directly; don't `source activate`.
- The bot trades real/paper money and sends Telegram messages on startup.
  **Two instances running at once can double-buy.** Verification must never
  start the bot. A manual instance may already be running (`pgrep -af
  leaps_spy`); nothing in this task may start the service while one is.
- `print` output must reach the journal promptly → run python unbuffered (`-u`).
- `.gitignore` ignores `*.json`, `*.log`, `.env`, `venv/` — new files here
  (`run.sh`, `deploy/*.service`) are not ignored and should be committed.
- Linger is already enabled for the user (`loginctl show-user $USER -p Linger`
  → `yes`), so a user unit with `WantedBy=default.target` starts at boot
  without a login.
- House style for user units: see `~/.config/systemd/user/decodable-reader.service`
  (header comment with install steps, `deploy/` folder in the repo).

## Steps

### 1. Launcher script — [x]

- **May edit:** `run.sh` (new).
- **Done when:** `run.sh` is executable (`chmod +x`), has a `#!/usr/bin/env bash`
  shebang, `set -euo pipefail`, `cd`s to the directory containing itself
  (resolving symlinks), and `exec`s `venv/bin/python -u leaps_spy.py "$@"`. If
  `venv/bin/python` is missing it prints a clear error to stderr and exits 1.
- **Verify (must not start the bot):**
  - `bash -n run.sh` passes; `test -x run.sh`.
  - Missing-venv path: copy `run.sh` into an empty temp dir and run it from
    another cwd → exits 1 with the error message.
  - cwd resolution: in a temp dir, copy `run.sh`, create a fake
    `venv/bin/python` that prints `$PWD` and its args, run `run.sh` via a
    symlink from a different cwd → prints the temp dir and `-u leaps_spy.py`.
- **Result:**
  - *Did:* created `run.sh` (mode 755): shebang, `set -euo pipefail`,
    `cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"`, a check
    `[[ ! -x venv/bin/python ]]` that prints
    `run.sh: <repo>/venv/bin/python not found. Create it with: python3 -m venv venv && venv/bin/pip install -r requirements.txt`
    to stderr and exits 1, then `exec venv/bin/python -u leaps_spy.py "$@"`.
  - *Verified* (scratchpad only, fake venv; the real bot was never run):
    `bash -n` exit 0; `test -x` exit 0; missing-venv copy run from another cwd
    → error message, exit 1; via relative and absolute symlink from other cwds
    → fake python prints `PWD=<temp dir>` and `ARGS=-u leaps_spy.py [extra args]`.
  - *Deliberately left:* the check uses `-x` (missing *or* not executable),
    slightly broader than "missing". `readlink -f` is GNU/Linux-specific —
    fine for this Linux-only systemd target, not portable to macOS. No
    single-instance lock in the launcher (out of scope for this step).
  - *For later steps:* `exec` means systemd's main PID is python itself, so
    `Type=simple` + `Restart=always` in step 2 track the bot directly. Since
    `run.sh` `cd`s itself, `WorkingDirectory=` in the unit is redundant but
    harmless; keep it per the plan. `run.sh` must stay executable in git
    (committed as mode 100755).

### 2. systemd user unit — [x]

- **May edit:** `deploy/leaps-spy.service` (new).
- **Done when:** unit follows the house style (header comment with install
  steps), `Type=simple`, `WorkingDirectory=` the repo root,
  `ExecStart=` absolute path to `run.sh`, `Restart=always`, `RestartSec=30`,
  `After=/Wants=network-online.target`, `WantedBy=default.target`.
  `Restart=always` (not on-failure) because a clean exit of a long-running
  trading loop is never intended.
- **Verify:** `systemd-analyze --user verify deploy/leaps-spy.service` reports
  no errors for this unit. Do **not** install, enable, or start it.
- **Result:**
  - *Did:* created `deploy/leaps-spy.service` (mode 644) following
    `decodable-reader.service`: header comment with a double-buy warning
    (stop any manual instance, `pgrep -af leaps_spy`), install steps
    (`cp`, `daemon-reload`, `enable` for next boot, separate `start` for now,
    `loginctl enable-linger`), the logs command, and a "fix paths if you move
    the repo" note. `[Unit]` `After=`/`Wants=network-online.target`;
    `[Service]` `Type=simple`,
    `WorkingDirectory=/home/shreyas/projects/workspace/alpaca_spy_leaps`,
    `ExecStart=/home/shreyas/projects/workspace/alpaca_spy_leaps/run.sh`,
    `Restart=always` (with a comment why), `RestartSec=30`; `[Install]`
    `WantedBy=default.target`.
  - *Verified:* `systemd-analyze --user verify deploy/leaps-spy.service` →
    exit 0, no messages about this unit (its only output is an unrelated
    system-unit warning, see Found along the way). Not installed:
    `systemctl --user list-unit-files 'leaps*'` → 0 unit files; nothing
    copied to `~/.config/systemd/user/`. The bot was never run.
  - *Deliberately left:* no `Environment=` lines (the bot reads `.env` from
    cwd). No `StartLimitIntervalSec=`/`StartLimitBurst=` — with
    `RestartSec=30` the default limit (5 starts / 10 s) can't trip. No
    single-instance guard (a manual run alongside the service is still
    possible; the header warns instead).
  - *For later steps:* `network-online.target` does **not** exist in the
    user manager (`systemctl --user show network-online.target` →
    `LoadState=not-found`), so `After=`/`Wants=` on it are no-ops for a user
    unit — kept because the plan requires them, but at boot the bot may
    start before the network is up. `Restart=always` + `RestartSec=30`
    covers a startup crash from no network; step 3's README should not
    claim the unit waits for the network. Step 3 should mirror the header's
    install commands and the "Run on startup" section name the header
    already points to.

### 3. README — [x]

- **May edit:** `README.md`.
- **Done when:** the Usage section documents `./run.sh`, and a new
  "Run on startup" section gives install/enable/start/stop/logs commands
  (`systemctl --user …`, `journalctl --user -u leaps-spy -f`) and warns to
  stop any manually started instance first.
- **Verify:** read the rendered section; commands match the unit name and
  paths from steps 1–2.
- **Result:**
  - *Did:* Usage now leads with `./run.sh` (works from any cwd, uses
    `venv/`), keeping `python leaps_spy.py` as the manual alternative. New
    "Run on startup" section (the name the unit header points to): what the
    unit does, the double-buy warning with `pgrep -af leaps_spy`, the install
    block copied verbatim from the header of `deploy/leaps-spy.service`
    (mkdir, cp, daemon-reload, enable, start, enable-linger), a manage block
    (status, stop, disable, `journalctl --user -u leaps-spy -f`), a
    "fix paths if you move the repo" note, and an explicit statement that
    the service does **not** wait for the network at boot and relies on the
    30 s restart instead.
  - *Verified:* read the rendered diff; unit name `leaps-spy`, path
    `deploy/leaps-spy.service`, `RestartSec=30`, and install commands match
    steps 1–2. Nothing run, installed, or committed.
  - *Deliberately left:* no macOS/Windows autostart instructions (Linux
    systemd only). Installation section's `source venv/bin/activate` flow
    unchanged; `run.sh` works with it since it only needs `venv/bin/python`.

### 3b. README network wording fix — [x]

Found while verifying step 3: the README says "if the bot starts before the
network is up and exits, systemd restarts it". That is wrong. `leaps_spy.py`
does not exit when offline: `send_telegram_message`, `send_current_positions`
and `init_telegram_polling` all swallow errors, and the main loop keeps retrying
(Telegram every ~2s, Alpaca every 10 min).

- **May edit:** `README.md` (only that one sentence in "Run on startup").
- **Done when:** the sentence says the service does not wait for the network,
  and a bot that starts offline keeps retrying on its own (the startup Telegram
  message may be lost), and `Restart=always` only covers a crash. It also warns
  briefly that Telegram commands sent while the bot was offline may be run once
  the network comes up (see Found along the way).
- **Verify:** `git diff README.md`; the claim matches `main()` in `leaps_spy.py`.
- **Result:**
  - *Did:* replaced the last sentence of the "Run on startup" closing
    paragraph with: no wait for network; an offline bot does not exit but
    retries (Telegram polling every few seconds, Alpaca every 10 minutes);
    startup Telegram message may be lost; `Restart=always` only covers a
    crash; Telegram commands sent while offline (including `/buy`) may be
    executed once the network comes up.
  - *Verified against code:* `main()` calls `send_telegram_message`,
    `send_current_positions`, `init_telegram_polling` (bare `except: pass`,
    returns `None`) once, then loops forever: `handle_telegram_updates`
    catches all exceptions and returns the unchanged id, followed by
    `time.sleep(2)` (plus up to a 10 s request timeout when offline); the
    Alpaca block is gated by `now_ts - last_strategy_check >= 600` and
    wrapped in `try/except`. With `last_update_id=None` no `offset` is
    sent, so pending updates are processed. Nothing run, installed, or
    committed.
  - *Deliberately left:* only that one sentence changed; the first
    paragraph's "restarts it 30 seconds after it exits" is still accurate.

### 4. Install (main agent, not a subagent) — [x]

Copy the unit to `~/.config/systemd/user/`, `daemon-reload`, `enable` (not
`--now`) so it starts on next boot. Starting now is left to the user, after they
stop the manual instance.

**Result (2026-09-25):** copied to `~/.config/systemd/user/leaps-spy.service`,
`daemon-reload`, `enable` → `is-enabled: enabled`, `is-active: inactive`.
Manual instance (PID 18679) left running and untouched.

## Found along the way

- `systemd-analyze --user verify` prints
  `/usr/lib/systemd/user/spice-vdagent.service:23: Unknown key 'StandardError' in section [Install], ignoring.`
  — a distro-packaged unit, unrelated to this task; harmless, not chased.
- User-manager `network-online.target` is `not-found` (see step 2 Result);
  if boot-time network races turn out to matter, a later task could add a
  wait-for-network in `run.sh` or handle it in `leaps_spy.py`.
- **Pre-existing, not fixed (behaviour change to trading code):** if
  `init_telegram_polling()` fails at startup (e.g. no network at boot), it
  returns `None`, so the first successful `handle_telegram_updates` polls with
  no `offset` and runs every pending update from the last 24h, including a
  `/buy` sent while the machine was off. When online at startup these are
  skipped. Booting on autostart makes this more likely. A fix would retry
  `init_telegram_polling` until it succeeds before entering the loop. It needs
  its own task.
