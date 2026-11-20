"""srt-build mcp - the lab for an agent, as an MCP server.

  srt-build mcp --trees ~/rt                  read, report and dry runs
  srt-build mcp --trees ~/rt --allow-submit   also build and submit

JSON-RPC 2.0 over stdin and stdout, one message per line (MCP over
stdio), like `srt mcp` of stable-rt-tools. Every tool runs srt-build
itself, without a terminal. Whoever starts the server decides what the
agent may do to the lab: building, installing and submitting kernels
(`lava`, `round start`, `round rerun`) only with --allow-submit,
removing rounds only with --allow-delete.

Building takes long: `lava` and `round start` run as background tasks,
which outlive the client; `task_status` follows them. A kernel tree is
named relative to --trees, e.g. v6.12-rt for ~/rt/v6.12-rt; one task
per tree at a time.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import IO, Callable

# The protocol versions this server speaks, newest first
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# The longest a command which isn't a task may take, seconds
TIMEOUT = 1800
# The most output a tool returns, characters
MAX_OUTPUT = 100_000
# The lines of a task's log task_status returns
LOG_TAIL = 60

SRT_BUILD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "srt-build")

INSTRUCTIONS = """\
Runs PREEMPT_RT test rounds in the LAVA lab with srt-build. The lab is
shared and the boards are taken while jobs run: submit only what the
maintainer asked for.

Read first: boards, rounds (the archive), round_status (LAVA),
round_compare. A release's test: lava builds the kernel of a tree
(e.g. v6.12-rt, the srt release), installs it for a board and submits
a test round; round_start submits a release round with the installed
kernels, with build true it builds and installs them first (dry_run
first). Both run as tasks: follow them with
task_status, then the round with round_status until finished, then
round_report (fetches the round into the archive and reports
problems) and round_compare against the previous round on the same
kernel. Judge results as doc/TUNING.md says: only a change beyond
about 40 % and 20 us is worth a look; report problems, not every job.

Submitting needs a server started with --allow-submit, removing a
round --allow-delete; a refused call means: ask the maintainer."""

_ROUND = re.compile(r"t?[0-9]+")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LIST = re.compile(r"[A-Za-z0-9_.-]+(,[A-Za-z0-9_.-]+)*")


class ToolError(Exception):
    """A tool call failed: the result reports it to the agent."""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[dict], dict]
    read_only: bool = False
    destructive: bool = False
    open_world: bool = True

    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                **self.schema,
            },
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.read_only,
                "openWorldHint": self.open_world,
            },
        }


@dataclass
class Result:
    exit_code: int
    stdout: str
    stderr: str


def run_srt_build(args, cwd):
    """Run srt-build args in cwd, without a terminal."""
    p = subprocess.run(
        [sys.executable, SRT_BUILD, *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
    )
    return Result(p.returncode, p.stdout, p.stderr)


def start_task(args, cwd, log, rc):
    """Start srt-build args in cwd in the background, in its own session
    so it outlives the server; output to log, the exit code to rc."""
    with open(log, "w") as out:
        p = subprocess.Popen(
            ["sh", "-c", '"$@"; echo $? > "$SRT_BUILD_RC"', "sh"]
            + [sys.executable, SRT_BUILD, *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, SRT_BUILD_RC=rc),
            start_new_session=True,
        )
    return p.pid


def default_state():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "srt-build", "mcp")


@dataclass
class Options:
    """What the one who starts the server decides, never the agent."""

    trees: str
    machines: dict = field(default_factory=dict)
    rounds: dict = field(default_factory=dict)
    allow_submit: bool = False
    allow_delete: bool = False
    state: str = field(default_factory=default_state)
    run: Callable = run_srt_build
    start: Callable = start_task


def _clip(text):
    if len(text) <= MAX_OUTPUT:
        return text
    return text[-MAX_OUTPUT:] + f"\n[{len(text) - MAX_OUTPUT} characters before]"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Server:
    """The tools, and the protocol."""

    def __init__(self, opts):
        self.opts = opts
        self.trees = os.path.abspath(opts.trees)
        self.tools = {t.name: t for t in self._tools()}

    # --- tool definitions -----------------------------------------------

    def _tools(self):
        rnd = {
            "round": {
                "type": "string",
                "description": "12 (release round), t3 (test round); "
                "default: the round started last",
            }
        }
        tree = {
            "tree": {
                "type": "string",
                "description": "the kernel tree, relative to the server's "
                "--trees, e.g. v6.12-rt",
            }
        }
        lists = {
            "flavors": {"type": "string", "description": "e.g. rt,nohz"},
            "tests": {"type": "string", "description": "e.g. cyclictest"},
            "testsuites": {
                "type": "string",
                "description": "default smoke; stress-ng-class for the stress "
                "classes",
            },
        }
        return [
            Tool(
                "boards",
                "The boards of the lab (config.yml), the flavors they can't "
                "build, and what a release round submits.",
                {},
                self._boards,
                read_only=True,
                open_world=False,
            ),
            Tool(
                "tests",
                "The test suites and tests per flavor (lava --list-tests).",
                {},
                lambda a: self._text(["lava", "--list-tests"]),
                read_only=True,
                open_world=False,
            ),
            Tool(
                "rounds",
                "The rounds in the archive: kernel, jobs, fetched, exported "
                "and the result line of their report.",
                {
                    "properties": {
                        "test": {
                            "type": "boolean",
                            "default": True,
                            "description": "also the test rounds",
                        }
                    }
                },
                self._rounds,
                read_only=True,
                open_world=False,
            ),
            Tool(
                "round_status",
                "State and health of every job of a round in LAVA, whether "
                "all finished, and LAVA's free disk.",
                {"properties": rnd},
                lambda a: self._json(["round", "status", *self._round(a)]),
                read_only=True,
            ),
            Tool(
                "round_compare",
                "Two rounds side by side from the archive: max latency per "
                "board, flavor, test and workload, the change in percent, "
                "the problems of both.",
                {
                    "properties": {
                        "a": {"type": "string", "description": "e.g. 12"},
                        "b": {"type": "string", "description": "e.g. t3"},
                    },
                    "required": ["a", "b"],
                },
                self._compare,
                read_only=True,
                open_world=False,
            ),
            Tool(
                "round_report",
                "Fetch the round's finished jobs into the archive and report "
                "every job with its problems. Deletes the archived uploads "
                "from Artifactorial (copies verified) unless keep_uploads.",
                {
                    "properties": {
                        **rnd,
                        "keep_uploads": {"type": "boolean", "default": False},
                    }
                },
                self._report,
            ),
            Tool(
                "round_export",
                "Send a round's results from the archive to VictoriaMetrics "
                "(the dashboards).",
                {
                    "properties": {
                        **rnd,
                        "dry_run": {"type": "boolean", "default": False},
                    }
                },
                self._export,
            ),
            Tool(
                "lava",
                "Build the kernel of the tree for a board, install it in the "
                "lab and submit a test round (a task). skip_build submits "
                "with the installed kernel. Needs --allow-submit.",
                {
                    "properties": {
                        **tree,
                        "board": {"type": "string", "description": "e.g. bbb"},
                        "skip_build": {"type": "boolean", "default": False},
                        **lists,
                        "split": {
                            "type": "boolean",
                            "default": False,
                            "description": "one job (boot) per test",
                        },
                    },
                    "required": ["tree", "board"],
                },
                self._lava,
                destructive=True,
            ),
            Tool(
                "round_start",
                "Submit a round with the installed kernels, every board and "
                "entry of config.yml rounds (in the tree); build: build and "
                "install every board's kernels first. A dry run renders "
                "the jobs and shows the warnings; the real one (a task) needs "
                "--allow-submit, and yes after the maintainer saw the "
                "warnings.",
                {
                    "properties": {
                        **tree,
                        "test": {
                            "type": "boolean",
                            "default": False,
                            "description": "a test round (t1, t2, ...)",
                        },
                        "boards": {"type": "string", "description": "e.g. bbb,c2d"},
                        "notes": {"type": "string"},
                        "build": {
                            "type": "boolean",
                            "default": False,
                            "description": "build and install the kernels first",
                        },
                        "dry_run": {"type": "boolean", "default": True},
                        "yes": {
                            "type": "boolean",
                            "default": False,
                            "description": "submit despite warnings",
                        },
                    },
                    "required": ["tree"],
                },
                self._round_start,
                destructive=True,
            ),
            Tool(
                "round_rerun",
                "Submit a job of a round again, e.g. after a lab failure; "
                "the new job replaces it. Needs --allow-submit.",
                {
                    "properties": {
                        "round": rnd["round"],
                        "job": {"type": "integer"},
                    },
                    "required": ["round", "job"],
                },
                self._rerun,
                destructive=True,
            ),
            Tool(
                "round_drop",
                "Remove a round: archive, uploads, and with metrics its "
                "series. A dry run lists it; the real one needs "
                "--allow-delete.",
                {
                    "properties": {
                        "round": rnd["round"],
                        "metrics": {"type": "boolean", "default": False},
                        "dry_run": {"type": "boolean", "default": True},
                    },
                    "required": ["round"],
                },
                self._drop,
                destructive=True,
            ),
            Tool(
                "task_status",
                "A task of lava or round_start: running, finished (exit "
                "code) or lost, and the end of its log.",
                {
                    "properties": {
                        "task": {"type": "string"},
                        "lines": {"type": "integer", "default": LOG_TAIL},
                    },
                    "required": ["task"],
                },
                self._task_status,
                read_only=True,
                open_world=False,
            ),
            Tool(
                "tasks",
                "The tasks of this server, newest first.",
                {},
                self._tasks,
                read_only=True,
                open_world=False,
            ),
        ]

    # --- helpers -----------------------------------------------------------

    def _srt_build(self, args, ok=(0,), cwd=None):
        r = self.opts.run(args, cwd or self.trees)
        if r.exit_code not in ok:
            raise ToolError(
                f"srt-build {' '.join(args)} failed with exit code "
                f"{r.exit_code}:\n{_clip(r.stdout)}{_clip(r.stderr)}"
            )
        return r

    def _text(self, args, ok=(0,), cwd=None):
        r = self._srt_build(args, ok, cwd)
        return {
            "command": "srt-build " + " ".join(args),
            "exit_code": r.exit_code,
            "output": _clip(r.stdout + r.stderr),
        }

    def _json(self, args, ok=(0,)):
        r = self._srt_build(args + ["--json"], ok)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError as err:
            raise ToolError(
                f"srt-build {' '.join(args)} --json gave no JSON ({err}):\n"
                f"{_clip(r.stdout)}{_clip(r.stderr)}"
            ) from err

    @staticmethod
    def _bool(args, key, default):
        v = args.get(key, default)
        if not isinstance(v, bool):
            raise ToolError(f"{key} must be a boolean")
        return v

    @staticmethod
    def _round_id(value, key="round"):
        if not isinstance(value, str) or not _ROUND.fullmatch(value):
            raise ToolError(f"{key} must be a round like 12 or t3")
        return value

    def _round(self, args):
        """The round argument of a round command, none for the newest."""
        if args.get("round") is None:
            return []
        return [self._round_id(args["round"])]

    @staticmethod
    def _list(args, key):
        v = args.get(key)
        if v is None:
            return []
        if not isinstance(v, str) or not _LIST.fullmatch(v):
            raise ToolError(f"{key} must be a comma separated list of names")
        return [f"--{key}", v]

    def _tree(self, args):
        name = args.get("tree")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ToolError("tree must be the name of a kernel tree, e.g. v6.12-rt")
        path = os.path.join(self.trees, name)
        if not os.path.isfile(os.path.join(path, "Makefile")):
            raise ToolError(f"{name} is not a kernel tree in {self.trees}")
        return path

    def _board(self, args):
        board = args.get("board")
        if not isinstance(board, str) or board not in self.opts.machines:
            raise ToolError(
                "board must be one of " + ", ".join(sorted(self.opts.machines))
            )
        return board

    def _need(self, allowed, flag, what):
        if not allowed:
            raise ToolError(
                f"{what} is not allowed: the server runs without {flag}. "
                f"Ask the maintainer to run it or to restart the server "
                f"with {flag}."
            )

    # --- tasks -------------------------------------------------------------

    def _task_file(self, task, ext):
        return os.path.join(self.opts.state, f"{task}.{ext}")

    def _load_tasks(self):
        if not os.path.isdir(self.opts.state):
            return []
        tasks = []
        for name in os.listdir(self.opts.state):
            if name.endswith(".json"):
                with open(os.path.join(self.opts.state, name)) as f:
                    tasks.append(json.load(f))
        return sorted(tasks, key=lambda t: t["started"], reverse=True)

    def _state_of(self, task):
        rc = self._task_file(task["id"], "rc")
        if os.path.exists(rc):
            with open(rc) as f:
                text = f.read().strip()
            return "finished", int(text) if text.isdigit() else None
        if _alive(task["pid"]):
            return "running", None
        return "lost", None

    def _task(self, args, cwd, what):
        """Start srt-build args in cwd as a task, one per tree."""
        for t in self._load_tasks():
            if t["cwd"] == cwd and self._state_of(t)[0] == "running":
                raise ToolError(f"task {t['id']} ({t['command']}) still runs in {cwd}")
        os.makedirs(self.opts.state, exist_ok=True)
        task = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        log, rc = self._task_file(task, "log"), self._task_file(task, "rc")
        pid = self.opts.start(args, cwd, log, rc)
        info = {
            "id": task,
            "command": "srt-build " + " ".join(args),
            "what": what,
            "cwd": cwd,
            "pid": pid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "log": log,
        }
        with open(self._task_file(task, "json"), "w") as f:
            json.dump(info, f)
        return {"task": task, "command": info["command"], "log": log}

    # --- tools -------------------------------------------------------------

    def _boards(self, args):
        return {
            "boards": {
                name: {"skip_flavors": m.get("skip_flavors") or []}
                for name, m in sorted(self.opts.machines.items())
            },
            "rounds": self.opts.rounds,
        }

    def _rounds(self, args):
        test = self._bool(args, "test", True)
        return self._json(["round", "list"] + (["--test"] if test else []))

    def _compare(self, args):
        a = self._round_id(args.get("a"), "a")
        b = self._round_id(args.get("b"), "b")
        return self._json(["round", "compare", a, b])

    def _report(self, args):
        keep = self._bool(args, "keep_uploads", False)
        cmd = ["round", "report", *self._round(args)]
        if keep:
            cmd.append("--keep-uploads")
        # 1: a job has problems, they are in the report
        return self._json(cmd, ok=(0, 1))

    def _export(self, args):
        cmd = ["round", "export", *self._round(args)]
        if self._bool(args, "dry_run", False):
            cmd.append("--dry-run")
        return self._text(cmd)

    def _lava(self, args):
        cwd = self._tree(args)
        board = self._board(args)
        cmd = ["lava", board]
        if self._bool(args, "skip_build", False):
            cmd.append("--skip-build")
        for key in ("flavors", "tests", "testsuites"):
            cmd += self._list(args, key)
        if self._bool(args, "split", False):
            cmd.append("--split")
        self._need(self.opts.allow_submit, "--allow-submit", "srt-build lava")
        return self._task(cmd, cwd, f"lava {board}")

    def _round_start(self, args):
        cwd = self._tree(args)
        cmd = ["round", "start"]
        if self._bool(args, "test", False):
            cmd.append("--test")
        cmd += self._list(args, "boards")
        notes = args.get("notes")
        if notes is not None:
            if not isinstance(notes, str) or "\n" in notes:
                raise ToolError("notes must be one line")
            cmd += ["--notes", notes]
        if self._bool(args, "build", False):
            cmd.append("--build")
        if self._bool(args, "dry_run", True):
            return self._text(cmd + ["--dry-run"], cwd=cwd)
        self._need(self.opts.allow_submit, "--allow-submit", "srt-build round start")
        if self._bool(args, "yes", False):
            cmd.append("--yes")
        return self._task(cmd, cwd, "round start")

    def _rerun(self, args):
        rnd = self._round_id(args.get("round"))
        job = args.get("job")
        if not isinstance(job, int) or isinstance(job, bool) or job < 1:
            raise ToolError("job must be a LAVA job id")
        self._need(self.opts.allow_submit, "--allow-submit", "srt-build round rerun")
        return self._text(["round", "rerun", rnd, str(job)])

    def _drop(self, args):
        cmd = ["round", "drop", self._round_id(args.get("round"))]
        if self._bool(args, "metrics", False):
            cmd.append("--metrics")
        if self._bool(args, "dry_run", True):
            return self._text(cmd + ["--dry-run"])
        self._need(self.opts.allow_delete, "--allow-delete", "srt-build round drop")
        return self._text(cmd + ["--yes"])

    def _task_status(self, args):
        task = args.get("task")
        tasks = {t["id"]: t for t in self._load_tasks()}
        if not isinstance(task, str) or task not in tasks:
            raise ToolError("no such task, see tasks")
        lines = args.get("lines", LOG_TAIL)
        if not isinstance(lines, int) or isinstance(lines, bool) or lines < 1:
            raise ToolError("lines must be a positive number")
        t = tasks[task]
        state, code = self._state_of(t)
        try:
            with open(t["log"], errors="replace") as f:
                tail = f.read().splitlines()[-lines:]
        except FileNotFoundError:
            tail = []
        return {**t, "state": state, "exit_code": code, "log_tail": tail}

    def _tasks(self, args):
        out = []
        for t in self._load_tasks():
            state, code = self._state_of(t)
            out.append({**t, "state": state, "exit_code": code})
        return {"tasks": out}

    # --- protocol ----------------------------------------------------------

    def handle(self, msg):
        """The response to msg, None for a notification."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        method, mid = msg.get("method"), msg.get("id")
        if "id" not in msg:
            return None  # notifications/initialized and the like
        if not isinstance(method, str):
            return _error(mid, INVALID_REQUEST, "no method")
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _error(mid, INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            return _result(mid, self._initialize(params))
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": [t.describe() for t in self.tools.values()]})
        if method == "tools/call":
            return self._call(mid, params)
        return _error(mid, METHOD_NOT_FOUND, f"unknown method {method}")

    def _initialize(self, params):
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "srt-build", "version": "1"},
            "instructions": INSTRUCTIONS,
        }

    def _call(self, mid, params):
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            return _error(mid, INVALID_PARAMS, f"unknown tool {params.get('name')}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(mid, INVALID_PARAMS, "arguments must be an object")
        unknown = set(args) - set(tool.schema.get("properties", {}))
        if unknown:
            return _error(mid, INVALID_PARAMS, f"unknown arguments: {sorted(unknown)}")
        try:
            out = tool.run(args)
        except (ToolError, OSError, subprocess.SubprocessError) as err:
            return _result(
                mid, {"content": [{"type": "text", "text": str(err)}], "isError": True}
            )
        return _result(
            mid,
            {
                "content": [{"type": "text", "text": json.dumps(out, default=str)}],
                "structuredContent": out,
                "isError": False,
            },
        )

    def serve(self, rd: IO[str], wr: IO[str]):
        """Answer the messages from rd on wr until rd ends."""
        for line in rd:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as err:
                resp = _error(None, PARSE_ERROR, str(err))
            else:
                resp = self.handle(msg)
            if resp is not None:
                wr.write(json.dumps(resp, default=str) + "\n")
                wr.flush()


def _result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def add_parser(subparser):
    p = subparser.add_parser(
        "mcp", help="serve the lab to an agent (MCP over stdin and stdout)"
    )
    p.add_argument(
        "--trees",
        default=os.curdir,
        help="the directory of the kernel trees (default: the current one)",
    )
    p.add_argument(
        "--allow-submit",
        action="store_true",
        help="let the agent build, install and submit kernels (lava, round "
        "start, round rerun)",
    )
    p.add_argument(
        "--allow-delete",
        action="store_true",
        help="let the agent remove rounds (round drop)",
    )
    p.set_defaults(func=cmd_mcp)


def cmd_mcp(args, system_config, machine_config):
    from .config import rounds

    if not os.path.isdir(args.trees):
        raise SystemExit(f"{args.trees} is not a directory")
    server = Server(
        Options(
            trees=args.trees,
            machines=machine_config,
            rounds=dict(rounds),
            allow_submit=args.allow_submit,
            allow_delete=args.allow_delete,
        )
    )
    # the client is gone: the tasks go on in their own sessions
    with contextlib.suppress(KeyboardInterrupt, BrokenPipeError):
        server.serve(sys.stdin, sys.stdout)
