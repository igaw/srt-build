"""srt-build mcp: the tools on fake srt-build runs, nothing reaches the lab."""

import json
import os
import subprocess
import sys

import pytest

from srt_build import mcp
from srt_build.mcp import Options, Result, Server

MACHINES = {"bbb": {"skip_flavors": ["lazy"]}, "c2d": {}}


class Fake:
    """Records the srt-build runs and tasks; answers from a table."""

    def __init__(self):
        self.runs = []
        self.tasks = []
        self.answers = {}
        self.pid = os.getpid()  # alive: the task runs

    def run(self, args, cwd):
        self.runs.append((args, cwd))
        return self.answers.get(tuple(args), Result(0, '{"ok": true}', ""))

    def start(self, args, cwd, log, rc):
        self.tasks.append((args, cwd))
        with open(log, "w") as f:
            f.write("building\nsubmitted job 42\n")
        return self.pid


@pytest.fixture
def lab(tmp_path):
    trees = tmp_path / "rt"
    (trees / "v6.12-rt").mkdir(parents=True)
    (trees / "v6.12-rt" / "Makefile").write_text("VERSION = 6\n")
    (trees / "not-a-tree").mkdir()
    fake = Fake()

    def server(**kw):
        return Server(
            Options(
                trees=str(trees),
                machines=MACHINES,
                rounds={"boards": ["bbb", "c2d"]},
                state=str(tmp_path / "state"),
                run=fake.run,
                start=fake.start,
                **kw,
            )
        )

    fake.server = server
    fake.tree = str(trees / "v6.12-rt")
    fake.state = tmp_path / "state"
    return fake


def call(server, name, **args):
    resp = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert resp is not None and "result" in resp, resp
    return resp["result"]


def ok(server, name, **args):
    result = call(server, name, **args)
    assert result["isError"] is False, result["content"][0]["text"]
    return result["structuredContent"]


def error(server, name, **args):
    result = call(server, name, **args)
    assert result["isError"] is True
    return result["content"][0]["text"]


def test_tools_and_annotations(lab):
    resp = lab.server().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    for name in ("boards", "tests", "rounds", "round_status", "round_compare"):
        assert tools[name]["annotations"]["readOnlyHint"], name
    for name in ("lava", "round_start", "round_rerun", "round_drop"):
        assert tools[name]["annotations"]["destructiveHint"], name
    assert all(not t["inputSchema"]["additionalProperties"] for t in tools.values())


def test_initialize(lab):
    resp = lab.server().handle(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert "--allow-submit" in resp["result"]["instructions"]


def test_read_tools(lab):
    s = lab.server()
    assert ok(s, "boards")["boards"]["bbb"] == {"skip_flavors": ["lazy"]}
    ok(s, "rounds")
    ok(s, "round_status", round="t3")
    ok(s, "round_status")
    ok(s, "round_compare", a="12", b="t3")
    assert [a for a, _ in lab.runs] == [
        ["round", "list", "--test", "--json"],
        ["round", "status", "t3", "--json"],
        ["round", "status", "--json"],
        ["round", "compare", "12", "t3", "--json"],
    ]


def test_bad_round(lab):
    for rnd in ("x", "12; rm", "-1"):
        assert "round like 12 or t3" in error(lab.server(), "round_status", round=rnd)
    assert lab.runs == []


def test_report_with_problems(lab):
    lab.answers[("round", "report", "--json")] = Result(1, '{"problems": 2}', "")
    assert ok(lab.server(), "round_report") == {"problems": 2}
    ok(lab.server(), "round_report", round="12", keep_uploads=True)
    assert lab.runs[-1][0] == ["round", "report", "12", "--keep-uploads", "--json"]


def test_no_json(lab):
    lab.answers[("round", "status", "--json")] = Result(1, "", "no rounds in /x\n")
    text = error(lab.server(), "round_status")
    assert "exit code 1" in text and "no rounds in /x" in text


def test_lava_needs_allow_submit(lab):
    text = error(lab.server(), "lava", tree="v6.12-rt", board="bbb")
    assert "--allow-submit" in text
    assert lab.tasks == []


def test_lava_task(lab):
    s = lab.server(allow_submit=True)
    out = ok(
        s, "lava", tree="v6.12-rt", board="bbb", skip_build=True, flavors="rt,nohz"
    )
    assert lab.tasks == [
        (["lava", "bbb", "--skip-build", "--flavors", "rt,nohz"], lab.tree)
    ]
    status = ok(s, "task_status", task=out["task"])
    assert status["state"] == "running"
    assert status["log_tail"] == ["building", "submitted job 42"]
    # one task per tree
    assert "still runs" in error(s, "lava", tree="v6.12-rt", board="c2d")
    # it finishes
    (lab.state / f"{out['task']}.rc").write_text("0\n")
    status = ok(s, "task_status", task=out["task"])
    assert (status["state"], status["exit_code"]) == ("finished", 0)
    assert ok(s, "tasks")["tasks"][0]["id"] == out["task"]
    ok(s, "lava", tree="v6.12-rt", board="c2d")


def test_lost_task(lab):
    lab.pid = 2**22 + 12345  # no such process
    s = lab.server(allow_submit=True)
    out = ok(s, "lava", tree="v6.12-rt", board="bbb")
    assert ok(s, "task_status", task=out["task"])["state"] == "lost"


def test_tree_and_board(lab):
    s = lab.server(allow_submit=True)
    for tree in ("../etc", "not-a-tree", "missing"):
        assert "tree" in error(s, "lava", tree=tree, board="bbb")
    assert "bbb, c2d" in error(s, "lava", tree="v6.12-rt", board="rpi9")
    assert "comma separated" in error(
        s, "lava", tree="v6.12-rt", board="bbb", tests="a b"
    )
    assert lab.tasks == []


def test_round_start(lab):
    ok(lab.server(), "round_start", tree="v6.12-rt", notes="rt24")
    assert lab.runs == [(["round", "start", "--notes", "rt24", "--dry-run"], lab.tree)]
    text = error(lab.server(), "round_start", tree="v6.12-rt", dry_run=False)
    assert "--allow-submit" in text
    s = lab.server(allow_submit=True)
    ok(s, "round_start", tree="v6.12-rt", test=True, dry_run=False, yes=True)
    assert lab.tasks == [(["round", "start", "--test", "--yes"], lab.tree)]
    assert "one line" in error(s, "round_start", tree="v6.12-rt", notes="a\nb")


def test_rerun_and_drop(lab):
    assert "--allow-submit" in error(lab.server(), "round_rerun", round="12", job=7)
    ok(lab.server(allow_submit=True), "round_rerun", round="12", job=7)
    ok(lab.server(), "round_drop", round="t2", metrics=True)
    assert "--allow-delete" in error(
        lab.server(), "round_drop", round="t2", dry_run=False
    )
    ok(lab.server(allow_delete=True), "round_drop", round="t2", dry_run=False)
    assert [a for a, _ in lab.runs] == [
        ["round", "rerun", "12", "7"],
        ["round", "drop", "t2", "--metrics", "--dry-run"],
        ["round", "drop", "t2", "--yes"],
    ]


def test_unknown_argument(lab):
    resp = lab.server().handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "rounds", "arguments": {"all": True}},
        }
    )
    assert "unknown arguments" in resp["error"]["message"]


def test_start_task_runs_in_the_background(tmp_path):
    """The real start_task: the exit code arrives in rc."""
    log, rc = str(tmp_path / "t.log"), str(tmp_path / "t.rc")
    pid = mcp.start_task(["--help"], str(tmp_path), log, rc)
    os.waitpid(pid, 0)
    assert (tmp_path / "t.rc").read_text().strip() == "0"
    assert "usage" in (tmp_path / "t.log").read_text()


def test_srt_build_mcp(tmp_path):
    """srt-build mcp answers on stdout, nothing else goes there."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "boards"},
        },
    ]
    p = subprocess.run(
        [sys.executable, mcp.SRT_BUILD, "mcp", "--trees", str(tmp_path)],
        input="".join(json.dumps(m) + "\n" for m in msgs),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    out = [json.loads(line) for line in p.stdout.splitlines()]
    assert [m["id"] for m in out] == [1, 2, 3]
    assert "lava" in [t["name"] for t in out[1]["result"]["tools"]]
    assert "bbb" in out[2]["result"]["structuredContent"]["boards"]
