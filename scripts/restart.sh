#!/bin/bash
# Drain-aware daemon restart: the only restart path (a bare kickstart killed a fable wake
# mid-run, 2026-08-12). Waits for inflight.json to empty, then bootout and bootstrap from
# ~/Library/LaunchAgents, then confirms the fresh start line landed in the log.
set -euo pipefail

launchd_label() {
    printf '%s\n' "${AGENT_TEAM_LAUNCHD_LABEL:-com.agent-team}"
}

# Only ~/Library/LaunchAgents is reloaded at login; a bootstrap from anywhere else lasts one
# boot session, which is how the fleet went deaf for 15 hours after the 2026-08-24 reboot.
plist_path() {
    printf '%s\n' "$HOME/Library/LaunchAgents/$(launchd_label).plist"
}

if [ "${1:-}" = "--selftest" ]; then
    test "$(unset AGENT_TEAM_LAUNCHD_LABEL; launchd_label)" = "com.agent-team"
    test "$(AGENT_TEAM_LAUNCHD_LABEL=com.example.agent-team launchd_label)" = "com.example.agent-team"
    test "$(HOME=/tmp/bob AGENT_TEAM_LAUNCHD_LABEL=com.example.agent-team plist_path)" \
        = "/tmp/bob/Library/LaunchAgents/com.example.agent-team.plist"
    echo "restart.sh selftest: 3 PASS, 0 FAIL"
    exit 0
fi

TIMEOUT_SEC="${1:-2100}"   # ~35 min default
POLL_SEC=15
CONFIRM_TIMEOUT_SEC=30

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="${AGENT_TEAM_LOGS_DIR:-$HOME/.config/agent-team/logs}"
LOG_PATH="$LOGS_DIR/listener.err.log"  # launchd routes the logger's stderr here
LABEL="$(launchd_label)"
PLIST="$(plist_path)"
BOOTSTRAP_TRIES=10

if [ ! -f "$PLIST" ]; then
    echo "restart.sh: no plist at $PLIST; render it per ADOPTING.md (Prepare the runtime)" >&2
    exit 1
fi

inflight_count() {
    PYTHONPATH="$SCRIPT_DIR" python3 -c "import store; print(len(store.inflight_all()))"
}

# A dead listener leaves its inflight rows behind, so draining on a job with no pid polls
# ghosts for the whole timeout. replay_inflight re-runs those rows at startup anyway.
if launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -q 'pid = '; then
    echo "restart.sh: waiting for inflight to drain (timeout ${TIMEOUT_SEC}s, poll ${POLL_SEC}s)"
    elapsed=0
    while true; do
        n="$(inflight_count)"
        if [ "$n" -eq 0 ]; then
            echo "restart.sh: drained, 0 inflight after ${elapsed}s"
            break
        fi
        if [ "$elapsed" -ge "$TIMEOUT_SEC" ]; then
            echo "restart.sh: TIMEOUT after ${TIMEOUT_SEC}s with $n still inflight; proceeding anyway"
            break
        fi
        sleep "$POLL_SEC"
        elapsed=$((elapsed + POLL_SEC))
    done
else
    echo "restart.sh: $LABEL not running, nothing to drain"
fi

# The listener imports from the main checkout, so pull that one, never the worktree this script
# may be sitting in: a merge pressed on GitHub moves the remote only, and a restart on the old
# code looks exactly like the fix not working.
MAIN_REPO="$(cd "$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
echo "restart.sh: git pull --ff-only in $MAIN_REPO"
git -C "$MAIN_REPO" pull --ff-only || echo "restart.sh: WARNING pull failed; restarting on the checkout as it stands"
echo "restart.sh: HEAD is $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

before_lines=0
if [ -f "$LOG_PATH" ]; then
    before_lines="$(wc -l < "$LOG_PATH")"
fi

# bootout then bootstrap, not kickstart: kickstart cannot load an unloaded job (the state after
# a reboot) and does not re-read an edited plist.
echo "restart.sh: launchctl bootout then bootstrap gui/$(id -u)/$LABEL from $PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
try=1
while true; do
    if launchctl bootstrap "gui/$(id -u)" "$PLIST"; then
        break
    fi
    if [ "$try" -ge "$BOOTSTRAP_TRIES" ]; then
        echo "restart.sh: bootstrap failed after ${try} tries; check $PLIST by hand" >&2
        exit 1
    fi
    echo "restart.sh: bootstrap try ${try} failed, retrying in 1s"
    try=$((try + 1))
    sleep 1
done

echo "restart.sh: confirming fresh start line in $LOG_PATH"
confirm_elapsed=0
while true; do
    if [ -f "$LOG_PATH" ] && tail -n "+$((before_lines + 1))" "$LOG_PATH" | grep -q "agent-team listener starting"; then
        echo "restart.sh: confirmed fresh start"
        exit 0
    fi
    if [ "$confirm_elapsed" -ge "$CONFIRM_TIMEOUT_SEC" ]; then
        echo "restart.sh: WARNING no fresh start line seen within ${CONFIRM_TIMEOUT_SEC}s; check $LOG_PATH by hand"
        exit 1
    fi
    sleep 2
    confirm_elapsed=$((confirm_elapsed + 2))
done
