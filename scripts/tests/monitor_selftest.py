"""Offline fixtures for monitor.py, run in the organ namespace."""

from pathlib import Path
import sys
from types import FunctionType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(module):
    return FunctionType(_body.__code__, module.__dict__)()


def _body():
    import datetime
    import json
    import pathlib
    import tempfile

    import api
    import constants
    import prompts
    import send as send_mod
    import store
    import tests.cases as cases

    passed = failed = 0
    # groups come from a fixture stream list through the real derivation, never from the live
    # domains.json: this estate's map is gitignored and its prefixes are nobody else's
    render_groups = constants.board_groups(
        ["setup", "maintenance", "unlisted-channel"], {"setup": "", "maintenance": ""})
    topic_groups = (("workshop", ("status", "setup")),)
    try:
        store.inflight_all()
        _ledger_rows("cost")
        _ledger_rows("kicks")
        passed += 3
    except (OSError, ValueError) as exc:
        failed += 1
        print("FAIL monitor state paths are not readable: %s" % exc)

    got = snapshot(**cases.MONITOR_INPUT)
    if got == cases.MONITOR_EXPECTED:
        passed += 1
    else:
        failed += 1
        print("FAIL snapshot(...) -> %r wanted %r" % (got, cases.MONITOR_EXPECTED))
    table = render_table(got)
    if table.startswith("Persona") and len(table.splitlines()) == len(got) + 1:
        passed += 1
    else:
        failed += 1
        print("FAIL rendered table is empty or incomplete")
    activity = render_activity(got)
    if activity.startswith("## Activity today\n\n| Persona |") \
            and len(activity.splitlines()) == len(got) + 4:
        passed += 1
    else:
        failed += 1
        print("FAIL activity Markdown table is empty or incomplete")
    lanes = lane_rows(**cases.MONITOR_LANE_INPUT)
    if lanes == cases.MONITOR_LANE_EXPECTED:
        passed += 1
    else:
        failed += 1
        print("FAIL lane_rows(...) -> %r wanted %r" % (lanes, cases.MONITOR_LANE_EXPECTED))
    lane_table = render_lanes(lanes)
    if "STUCK" in lane_table and lane_table.count("maat") == 2 and "-" in lane_table:
        passed += 1
    else:
        failed += 1
        print("FAIL rendered lanes lost duplicate personas, idle fallback, or STUCK")
    for seconds, expected in cases.MONITOR_AGES:
        got_age = format_age(seconds)
        if got_age == expected:
            passed += 1
        else:
            failed += 1
            print("FAIL format_age(%r) -> %r wanted %r" % (seconds, got_age, expected))
    for now_ts, timestamp, expected in cases.BOARD_ITEM_VISIBILITY:
        got_visibility = _show_digest_items({"timestamp": timestamp}, now_ts)
        if got_visibility == expected:
            passed += 1
        else:
            failed += 1
            print("FAIL _show_digest_items(%r, %r) -> %r wanted %r" %
                  (now_ts, timestamp, got_visibility, expected))
    merged = merge_todos(*cases.BOARD_TODO_INPUT)
    if merged == cases.BOARD_TODO_EXPECTED:
        passed += 1
    else:
        failed += 1
        print("FAIL merge_todos(...) -> %r wanted %r" % (merged, cases.BOARD_TODO_EXPECTED))
    board = render_board(
        cases.BOARD_RENDER_LANES, got, cases.BOARD_RENDER_TOPICS,
        cases.BOARD_RENDER_DIGESTS, now_ts=200000, groups=render_groups)
    if all(part in board for part in cases.BOARD_RENDER_CONTAINS) and \
            all(part not in board for part in cases.BOARD_RENDER_FORBIDDEN):
        passed += 1
    else:
        failed += 1
        print("FAIL render_board(...) missing a required section or link")
    saved_todo_sources = _loop_todos, _topic_todos
    rendered_groups = []
    try:
        globals()["_loop_todos"] = lambda as_name: []
        globals()["_topic_todos"] = lambda as_name, now_ts=None, groups=None, streams=None: \
            rendered_groups.append(groups) or []
        render_board([], {}, digests={}, parked=[], groups=render_groups)
    finally:
        globals()["_loop_todos"], globals()["_topic_todos"] = saved_todo_sources
    if rendered_groups == [render_groups]:
        passed += 1
    else:
        failed += 1
        print("FAIL render_board groups did not reach _topic_todos: %r" % rendered_groups)
    parked_board = render_board(
        cases.BOARD_RENDER_LANES, got, cases.BOARD_RENDER_TOPICS,
        cases.BOARD_RENDER_DIGESTS, now_ts=200000, parked=cases.BOARD_RENDER_PARKED,
        groups=render_groups)
    if all(part in parked_board for part in cases.BOARD_PARKED_CONTAINS) \
            and all(part not in parked_board for part in cases.BOARD_PARKED_FORBIDDEN):
        passed += 1
    else:
        failed += 1
        print("FAIL parked render lost its spoiler, link, or live lane")
    combined_parts = board_parts(
        10000, cases.BOARD_RENDER_LANES, got, cases.BOARD_RENDER_TOPICS,
        cases.BOARD_RENDER_DIGESTS, now_ts=200000, groups=render_groups)
    split_parts = board_parts(
        1, cases.BOARD_RENDER_LANES, got, cases.BOARD_RENDER_TOPICS,
        cases.BOARD_RENDER_DIGESTS, now_ts=200000, groups=render_groups)
    # the fixture's own prefixes, not the live config: domains.json is gitignored, so a board
    # asserted against this estate's map is red on every other one
    fixture_sections = ("activity",) + tuple(prefix for prefix, _ in render_groups)
    default_board = render_board(
        cases.BOARD_RENDER_LANES, got, cases.BOARD_RENDER_TOPICS,
        cases.BOARD_RENDER_DIGESTS, now_ts=200000, groups=render_groups)
    if combined_parts == {"activity": default_board} \
            and tuple(split_parts) == fixture_sections:
        passed += 1
    else:
        failed += 1
        print("FAIL board_parts combined=%r split=%r" %
              (list(combined_parts), list(split_parts)))

    saved_topics = (api.visible_streams, api.stream_id, api.topics, api.load, _message)
    topic_calls = []
    try:
        api.visible_streams = lambda as_name: ["status", "setup"]
        api.stream_id = lambda as_name, channel: 9 if channel == "status" else 7
        api.topics = lambda as_name, stream_id: ([
            {"name": constants.BOARD_TOPIC, "max_id": 12},
        ] if stream_id == 9 else [
            {"name": "recent", "max_id": 11},
            {"name": constants.RESOLVED_PREFIX + " done", "max_id": 10},
            {"name": "old", "max_id": 9},
            {"name": "older", "max_id": 8},
        ])
        api.load = lambda as_name: {"site": "https://example"}
        globals()["_message"] = lambda as_name, message_id: topic_calls.append(message_id) or {
            "timestamp": {12: 999950, 11: 999900, 9: 100, 8: 50}[message_id]}
        recent = _topic_todos("bridge", now_ts=1000000, groups=topic_groups)
    finally:
        api.visible_streams, api.stream_id, api.topics, api.load = saved_topics[:4]
        globals()["_message"] = saved_topics[4]
    if recent == cases.BOARD_RECENT_EXPECTED and topic_calls == [12, 11, 9]:
        passed += 1
    else:
        failed += 1
        print("FAIL recent topic sweep -> %r calls=%r" % (recent, topic_calls))

    park_state = {"7:Build board": 1, "9:resolved": 2}

    def mutate_parked(name, fn):
        result = fn(park_state)
        if isinstance(result, dict) and result is not park_state:
            park_state.clear()
            park_state.update(result)

    parked = parked_topics(
        topics=cases.PARK_TOPICS, load_fn=lambda name: dict(park_state),
        mutate_fn=mutate_parked)
    if parked == [cases.PARK_TOPICS[0]] and park_state == {"7:Build board": 1}:
        passed += 1
    else:
        failed += 1
        print("FAIL parked_topics prune -> %r state=%r" % (parked, park_state))

    unresolved = unresolved_topics(
        "bob", stream_id_fn=lambda as_name, channel: 7 if channel == "setup" else None,
        topics_fn=lambda as_name, stream_id: cases.PARK_API_TOPICS,
        load_fn=lambda as_name: {"site": "https://example"},
        groups=(("workshop", ("setup",)),))
    if unresolved == cases.PARK_API_EXPECTED:
        passed += 1
    else:
        failed += 1
        print("FAIL unresolved_topics -> %r wanted %r" %
              (unresolved, cases.PARK_API_EXPECTED))

    park_state = {}
    parked_row = set_parked(
        "setup", "Build board", True, topics=cases.PARK_TOPICS,
        mutate_fn=mutate_parked, now_ts=1234)
    parked_state = dict(park_state)
    unparked_row = set_parked(
        "setup", "Build board", False, topics=cases.PARK_TOPICS,
        mutate_fn=mutate_parked, now_ts=1235)
    try:
        set_parked("setup", "Build bord", True, topics=cases.PARK_TOPICS,
                   mutate_fn=mutate_parked)
        mismatch = "accepted"
    except ValueError as exc:
        mismatch = str(exc)
    if parked_row == cases.PARK_TOPICS[0] and unparked_row == cases.PARK_TOPICS[0] \
            and parked_state == {"7:Build board": 1234} and park_state == {} \
            and "Build board" in mismatch:
        passed += 1
    else:
        failed += 1
        print("FAIL set_parked exact control -> %r %r %r %r" %
              (parked_row, unparked_row, parked_state, mismatch))

    refreshes, sweeps, board_refreshes = [], [], []
    update_stub = lambda **kwargs: board_refreshes.append(kwargs) or {"activity": (99, False)}
    single_refresh = refresh_board(
        "setup", "Build board", topics=cases.PARK_TOPICS,
        refresh_fn=lambda *args, **kwargs: refreshes.append((args, kwargs)),
        update_fn=update_stub)
    digest_refresh = refresh_board(
        digests=True, sweep_fn=lambda as_name: sweeps.append(as_name), update_fn=update_stub)
    board_refresh = refresh_board(update_fn=update_stub)
    if refreshes == [((constants.BRIDGE_IDENTITY, 7, "setup", "Build board"), {"force": True})] \
            and sweeps == [constants.BRIDGE_IDENTITY] \
            and board_refreshes == [{"as_name": constants.BRIDGE_IDENTITY}] * 3 \
            and single_refresh == digest_refresh == board_refresh == {"activity": (99, False)}:
        passed += 1
    else:
        failed += 1
        print("FAIL refresh_board modes -> %r %r %r" %
              (refreshes, sweeps, board_refreshes))

    states, current, boards = {}, {}, []
    saved = store.load, store.mutate, send_mod.board_message
    try:
        store.load = lambda name: dict(states.get(name, {}))

        def mutate_state(name, fn):
            states[name] = fn(dict(states.get(name, {})))

        def board_stub(as_name, channel, topic, body, message_id=None):
            boards.append((as_name, channel, topic, body, message_id))
            if message_id is None:
                message_id = 98 + len([row for row in boards if row[4] is None])
                current[message_id] = body
                return message_id, True
            if current.get(message_id) == body:
                return message_id, False
            current[message_id] = body
            return message_id, True

        store.mutate = mutate_state
        send_mod.board_message = board_stub
        first = update_board(content="one")
        unchanged = update_board(content="one")
        changed = update_board(content="two")
        split = update_board(contents={
            "activity": "activity", "workshop": "workshop", "domains": "domains"})
    finally:
        store.load, store.mutate, send_mod.board_message = saved
    if first == {"activity": (99, True)} and unchanged == {"activity": (99, False)} \
            and changed == {"activity": (99, True)} \
            and split == {"activity": (99, True), "workshop": (100, True),
                          "domains": (101, True)} \
            and states == {"board": {"message_id": 99},
                           "board-workshop": {"message_id": 100},
                           "board-domains": {"message_id": 101}} \
            and [row[2] for row in boards] == [constants.BOARD_TOPIC] * 6 \
            and [row[4] for row in boards] == [None, 99, 99, 99, None, None]:
        passed += 1
    else:
        failed += 1
        print("FAIL update_board sequence: %r %r %r split=%r states=%r boards=%r" %
              (first, unchanged, changed, split, states, boards))

    states = {"board": {"message_id": 99, "failed": True}}
    saved = store.load, store.mutate, send_mod.board_message
    try:
        store.load = lambda name: dict(states.get(name, {}))

        def mutate_replacement_state(name, fn):
            states[name] = fn(dict(states.get(name, {})))

        store.mutate = mutate_replacement_state
        send_mod.board_message = lambda *args: (199, True)
        replacement = update_board(content="replacement")
    finally:
        store.load, store.mutate, send_mod.board_message = saved
    if replacement == {"activity": (199, True)} \
            and states == {"board": {"message_id": 199}}:
        passed += 1
    else:
        failed += 1
        print("FAIL update_board replacement id: %r states=%r" % (replacement, states))

    states = {
        "board": {"message_id": 99},
        "board-workshop": {"message_id": 100},
        "board-domains": {"message_id": 101},
    }
    alerts, update_attempts = [], []
    fail_activity = [True]
    saved = store.load, store.mutate, send_mod.post, send_mod.board_message
    log_disabled = log.disabled
    try:
        store.load = lambda name: dict(states.get(name, {}))

        def mutate_failure_state(name, fn):
            states[name] = fn(dict(states.get(name, {})))

        def board_section(as_name, channel, topic, body, message_id=None):
            update_attempts.append(message_id)
            if message_id == 99 and fail_activity[0]:
                raise SystemExit("414")
            return message_id, True

        store.mutate = mutate_failure_state
        send_mod.post = lambda *args: alerts.append(args) or 200
        send_mod.board_message = board_section
        log.disabled = True
        isolated = update_board(contents={
            "activity": "new activity", "workshop": "new workshop", "domains": "new domains"})
        repeated = update_board(contents={"activity": "new activity"})
        failed_state = dict(states["board"])
        fail_activity[0] = False
        recovered = update_board(contents={"activity": "new activity"})
    finally:
        store.load, store.mutate, send_mod.post, send_mod.board_message = saved
        log.disabled = log_disabled
    if isolated == {"activity": (99, None), "workshop": (100, True),
                    "domains": (101, True)} \
            and repeated == {"activity": (99, None)} \
            and recovered == {"activity": (99, True)} \
            and failed_state == {"message_id": 99, "failed": True} \
            and states["board"] == {"message_id": 99} and len(alerts) == 1 \
            and alerts[0][1:3] == (constants.STATUS_STREAM, constants.ALERTS_TOPIC) \
            and prompts.BOARD_UPDATE_ALERT.format(section="activity") == alerts[0][3]:
        passed += 1
    else:
        failed += 1
        print("FAIL update_board isolation: %r %r %r state=%r alerts=%r attempts=%r" %
              (isolated, repeated, recovered, states, alerts, update_attempts))

    class _Proc:
        def __init__(self, stdout, returncode=0):
            self.stdout, self.returncode = stdout, returncode

    launchd_commands = []

    def run_daemon(command, **kwargs):
        launchd_commands.append(command)
        return _Proc(cases.MONITOR_LAUNCHD_PRINT if command[0] == "launchctl"
                     else cases.MONITOR_LAUNCHD_START)

    live = launchd_status("com.agent-team", run=run_daemon, uid_fn=lambda: 501)
    gone = launchd_status("com.agent-team", run=lambda *a, **k: _Proc("", 3),
                          uid_fn=lambda: 501)
    started_ts = datetime.datetime(2026, 8, 25, 11, 4, 0).timestamp()
    if live == {"pid": 9947, "started": started_ts} \
            and launchd_commands == [["launchctl", "print", "gui/501/com.agent-team"],
                                     ["ps", "-o", "lstart=", "-p", "9947"]] \
            and gone == {"pid": None, "started": None}:
        passed += 1
    else:
        failed += 1
        print("FAIL launchd_status -> %r gone=%r commands=%r" % (live, gone, launchd_commands))

    def raising_fetch(url, timeout=None):
        raise OSError("refused")

    if health_ok("http://127.0.0.1:1/health", fetch=raising_fetch) is False:
        passed += 1
    else:
        failed += 1
        print("FAIL health_ok did not swallow a refused connection")

    class _HealthResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def getcode(self):
            return 200

    health_requests = []

    def recording_fetch(request, timeout=None):
        health_requests.append((request, timeout))
        return _HealthResponse()

    healthy = health_ok("https://voice.example/health", fetch=recording_fetch)
    request, timeout = health_requests[0]
    if healthy and request.full_url == "https://voice.example/health" \
            and request.get_header("User-agent") == "agent-team-monitor/1.0" \
            and timeout == 2:
        passed += 1
    else:
        failed += 1
        print("FAIL health_ok request -> %r timeout=%r" % (request.__dict__, timeout))

    checked = []
    rows = daemon_rows(
        cases.MONITOR_DAEMONS,
        status_fn=lambda label: {"pid": 9947, "started": 1200.0} \
            if label == "com.agent-team" else {"pid": None, "started": None},
        health_fn=lambda url: checked.append(url) or False)
    if rows == [{"label": "com.agent-team", "pid": 9947, "started": 1200.0, "health": False},
                {"label": "com.mate.voice-connector", "pid": None, "started": None,
                 "health": None}] \
            and checked == ["http://127.0.0.1:1/health"]:
        passed += 1
    else:
        failed += 1
        print("FAIL daemon_rows -> %r checked=%r" % (rows, checked))

    step = constants.PROGRESS_MIN * 60
    body = render_daemons(rows, now_ts=4800.0)
    late = render_daemons(rows, now_ts=4800.0 + step - 1)
    next_step = render_daemons(rows, now_ts=4800.0 + step)
    if prompts.DAEMON_RUNNING in body and prompts.DAEMON_MISSING in body \
            and prompts.DAEMON_HEALTH_DOWN in body and prompts.DAEMON_HEALTH_NONE in body \
            and "9947" in body and "1h 00m" in body and body.count("_As of ") == 1 \
            and body == late and body != next_step:
        passed += 1
    else:
        failed += 1
        print("FAIL render_daemons -> %r stable=%r stepped=%r"
              % (body, body == late, body != next_step))

    states = {}
    sent = []
    saved = store.load, store.mutate, send_mod.board_message
    try:
        store.load = lambda name: dict(states.get(name, {}))

        def mutate_daemon_state(name, fn):
            states[name] = fn(dict(states.get(name, {})))

        def daemon_board(as_name, channel, topic, body, message_id=None):
            sent.append((as_name, channel, topic, message_id))
            return (message_id or 77), message_id is None

        store.mutate = mutate_daemon_state
        send_mod.board_message = daemon_board
        first = update_daemons(body="daemons")
        again = update_daemons(body="daemons")
    finally:
        store.load, store.mutate, send_mod.board_message = saved
    if first == (77, True) and again == (77, False) \
            and states == {constants.DAEMONS_STATE: {"message_id": 77}} \
            and [row[1:3] for row in sent] == \
            [(constants.STATUS_STREAM, constants.DAEMONS_TOPIC)] * 2:
        passed += 1
    else:
        failed += 1
        print("FAIL update_daemons -> %r %r states=%r sent=%r" % (first, again, states, sent))

    # domain_board: the id lives in the domain repo, so each row gets its own throwaway root.
    for label, channel, root, body, window, resolves, state, refusal in cases.DOMAIN_BOARDS:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / constants.DOMAIN_BOARD_STATE
            if state is not None:
                path.write_text(state if isinstance(state, str) else json.dumps(state))
            sent = []

            def board_stub(as_name, channel, topic, body, message_id=None):
                sent.append((as_name, channel, topic, body, message_id))
                return (message_id or 55), True

            log_disabled = log.disabled
            try:
                log.disabled = True
                got = domain_board(channel, body, root=(tmp if root else ""),
                                   window_fn=lambda name: window, board_fn=board_stub,
                                   stream_id_fn=lambda name, ch: 7 if resolves else None,
                                   stamp_fn=lambda: "STAMP")
                error = None
            except ValueError as exc:
                got, error = None, str(exc)
            finally:
                log.disabled = log_disabled
            written = json.loads(path.read_text()) if path.is_file() else None
            status = constants.DOMAIN_STATUS_CHANNEL.format(channel=channel)
            if refusal:
                ok = error is not None and refusal in error and not sent
            else:
                # only a state file naming this exact destination hands its id over; anything
                # else posts fresh, or the board would be edited where it no longer belongs
                here = isinstance(state, dict) and \
                    (state.get("channel"), state.get("topic")) == (status, constants.BOARD_TOPIC)
                prior = state.get("message_id") if here else None
                # the tool stamps the first line, so what is sent is never the body handed in
                ok = (error is None and got == ((prior or 55), True)
                      and len(sent) == 1
                      and sent[0][1] == status
                      and sent[0][2] == constants.BOARD_TOPIC
                      and sent[0][3] == "STAMP\n\n" + body
                      and sent[0][4] == prior
                      and written == {"channel": status, "topic": constants.BOARD_TOPIC,
                                      "message_id": prior or 55})
            if ok:
                passed += 1
            else:
                failed += 1
                print("FAIL domain_board %s -> %r error=%r sent=%r written=%r" %
                      (label, got, error, sent, written))

    print("monitor.py selftest: %d PASS, %d FAIL" % (passed, failed))
    return 1 if failed else 0
