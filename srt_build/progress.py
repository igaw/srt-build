"""Progress of the long steps: round wait and round start.

`round wait` waits for a round for hours (`srt test` of stable-rt-tools
runs it), `round start` builds every flavor of every board first. Both
tell where they are: on a terminal one line updated in place, else a
plain line when something changed (at least every 30 minutes).

The estimates come from earlier runs: a job's duration in the newest
earlier round of the archive with the same board, flavor and test; a
build's duration from the last build of that board and flavor
(build-times.json in the cache).
"""

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

from .archive import ArchiveApi, counted_jobs, load_round, round_dir, round_ids

# a non-terminal gets the line again after this long, changed or not
QUIET_SECONDS = 30 * 60
QUEUED = ("Submitted", "Scheduling", "Scheduled")


def clock():
    return time.time()


def parse_time(value):
    """LAVA's or round.yaml's UTC time as seconds since the epoch; None
    if there is none."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def duration(seconds):
    """3h12m, 45m, 3m05s (under ten minutes), 40s."""
    seconds = max(0, int(round(seconds)))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m >= 10:
        return f"{m}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class Progress:
    """One progress line: in place on a terminal, else printed when it
    changed (key) or every QUIET_SECONDS. Other lines (failures,
    warnings) go above it through message()."""

    def __init__(self, out=None, quiet=False, now=None):
        self.out = out or sys.stdout
        self.quiet = quiet
        self.now = now or clock
        try:
            self.tty = self.out.isatty()
        except (AttributeError, ValueError):
            self.tty = False
        self.line = None  # what the terminal shows now
        self.key = None
        self.printed = None  # when the last plain line went out

    def show(self, line, key=None):
        """The progress line; key: what counts as a change (default the
        line itself)."""
        if self.quiet:
            return
        key = line if key is None else key
        if self.tty:
            self.out.write("\r" + line + "\x1b[K")
            self.out.flush()
            self.line = line
            return
        t = self.now()
        if key != self.key or self.printed is None or t - self.printed >= QUIET_SECONDS:
            print(line, file=self.out, flush=True)
            self.key, self.printed = key, t

    def clear(self):
        if self.tty and self.line is not None:
            self.out.write("\r\x1b[K")
            self.out.flush()
            self.line = None

    def message(self, text, file=None):
        """A line of its own, above the progress line."""
        line = self.line
        self.clear()
        print(text, file=file or self.out, flush=True)
        if line is not None:
            self.show(line)


#
# round wait: how long the jobs take
#


def job_seconds(job):
    """How long a finished job ran, from job.json; None if unknown."""
    start, end = parse_time(job.get("start_time")), parse_time(job.get("end_time"))
    if start is None or end is None or end < start:
        return None
    return end - start


def job_history(archive, before, kind, keys):
    """{(board, flavor, test): seconds} for keys: the duration in the
    newest round of the archive started before `before`, rounds of kind
    first, then any."""
    rounds = []
    for rid in round_ids(archive):
        info = load_round(archive, rid)
        started = parse_time(info.get("started"))
        if started is None or before is not None and started >= before:
            continue
        rounds.append((started, rid, info))
    rounds.sort(key=lambda r: r[0], reverse=True)
    found = {}
    for same_kind in (True, False):
        for _, rid, info in rounds:
            if (info.get("kind") == kind) != same_kind:
                continue
            missing = {k for k in keys if k not in found}
            if not missing:
                return found
            a = ArchiveApi(round_dir(archive, rid))
            for jid in counted_jobs(info):
                e = info["jobs"][jid]
                key = (e.get("board"), e.get("flavor"), e.get("test"))
                if key not in missing or not a.has(jid):
                    continue
                seconds = job_seconds(a.job(jid))
                if seconds is not None:
                    found[key] = seconds
                    missing.discard(key)
    return found


def jobs_left(jobs, history, now):
    """Seconds until the jobs are done: per board one after the other,
    the boards side by side, so the longest board. jobs: (board, flavor,
    test, state, start_time) of the jobs not finished. A job without
    history counts the median of its board's known ones; None when a
    board has a job with none at all."""
    boards = {}
    for board, flavor, test, state, start in jobs:
        boards.setdefault(board, []).append((flavor, test, state, start))
    longest = 0.0
    for board, todo in boards.items():
        known = [s for (b, _, _), s in history.items() if b == board]
        fallback = statistics.median(known) if known else None
        total = 0.0
        for flavor, test, state, start in todo:
            expected = history.get((board, flavor, test), fallback)
            if expected is None:
                return None
            if state not in QUEUED and start is not None:
                expected = max(0.0, expected - (now - start))
            total += expected
        longest = max(longest, total)
    return longest


def wait_line(rid, counts, elapsed, left, batch=None):
    """round 20: 31/54 finished (1 not Complete), 2 running, 21 queued,
    3h12m so far, about 2h40m left; counts: finished, total, bad,
    running, queued."""
    finished, total, bad, running, queued = counts
    head = f"round {rid}" if batch is None else f"batch {batch[0]}, round {rid}"
    if batch is not None:
        head += f" ({batch[1]} of {batch[2]})"
    text = f"{head}: {finished}/{total} finished"
    if bad:
        text += f" ({bad} not Complete)"
    text += f", {running} running, {queued} queued"
    if elapsed is not None:
        text += f", {duration(elapsed)} so far"
    if left is not None:
        text += f", about {duration(left)} left"
    return text


#
# round start: how long the builds take
#


def build_times_path(system_config):
    """The build times, next to the build directory's cache."""
    base = system_config.get("base-build-path") or os.path.expanduser(
        "~/.cache/srt-build/build"
    )
    return os.path.join(os.path.dirname(os.path.abspath(base)), "build-times.json")


def load_build_times(path):
    """{"board flavor": seconds}; {} when there is none or it's broken."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): float(v)
        for k, v in data.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def save_build_time(path, board, flavor, seconds):
    """Remember a build's duration (atomically; a failure is no error)."""
    times = load_build_times(path)
    times[f"{board} {flavor}"] = round(seconds, 1)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(times, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"warning: build times not saved: {exc}", file=sys.stderr)


def builds_left(times, builds):
    """Seconds of the builds (board, flavor) by their last durations;
    None when one has none."""
    total = 0.0
    for board, flavor in builds:
        seconds = times.get(f"{board} {flavor}")
        if seconds is None:
            return None
        total += seconds
    return total
