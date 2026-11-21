"""The rt-tests Grafana dashboards, for the samples of `jobs export`.

`srt-build jobs dashboard DIR` writes them; homelab provisions the
files (grafana_dashboard_files on monitor). Edit this and rerun, not
the JSON.

  rt-tests.json        "RT tests": the overview, by round. One row
                       per board, in it one trend per test with the
                       release rounds on the x axis (max latency of
                       each round, a line per flavor and workload). A
                       click on a trend opens:
  rt-test-detail.json  "RT test detail": one board, flavor and test.
                       Per thread and percentiles over the rounds of
                       the chosen kinds (release by default; test
                       rounds as lines of their own, "(test)", t5 at
                       x 5), one round's histogram and threads, the
                       rounds, jobs, problems and kernels.
  rt-rounds-compared.json "RT rounds compared": two rounds (release or
                       test, chosen at the top) side by side, a bar
                       per board, test and workload.
  rt-problems.json     "RT problems": the jobs with problems, and the
                       jobs, the worst max latency and the srt-build
                       versions over all jobs chosen.

`round export` labels the samples with round and round_kind. The round
trends use Grafana's Trend panel (Grafana 10 or later): the round, a
label, becomes the x value, so only release rounds (numbers) go into
the overview's; test rounds (t3) are compared in RT rounds compared and
can be picked as the round in depth. The detail's trends follow the
round kind: by_kind gives each round a number label n and test rounds
their own lines. The round_kind variable (release by default)
keeps test rounds out of everything else unless chosen; samples
without the label (jobs outside the archive) still count in the tables.
The workload variable picks the background load (idle, hackbench,
stress-ng-class-<c>, ...).

Every job is a handful of samples at the job's end time, not a
continuous series: the panels are instant queries that take the
largest value over the dashboard's time range (a year), grouped by
round. Time is no axis: when a round ran is in the Rounds table.
"""

DS = {"type": "prometheus", "uid": "victoriametrics"}
OVERVIEW_UID = "rt-tests"
DETAIL_UID = "rt-test-detail"
COMPARE_UID = "rt-rounds-compared"
PROBLEMS_UID = "rt-problems"

# Samples of the chosen round kinds, and those without round (jobs
# export): "" matches a missing label.
KIND = 'round_kind=~"$round_kind|"'
# The background load of a test's samples (results only; the job-level
# series have no workload). All is .*, which also matches a missing one.
WL = 'workload=~"$workload"'
# For the job counts and problems: all tests, also those without
# latencies (smoke-tests, isolcpus, pi-stress), which $test leaves out.
JOBS = 'board=~"$board", flavor=~"$flavor", kernel=~"$kernel", ' + KIND
BY = "board, flavor, test"
# The detail dashboard's: one board, flavor and test.
ONE = (
    'board="$board", flavor="$flavor", test="$test", kernel=~"$kernel", '
    + WL
    + ", "
    + KIND
)
# Round samples only, of the chosen kinds.
ROUNDS = 'round_kind=~"$round_kind"'
# The round trends: release rounds only, their round is a number.
RELEASE = 'round_kind="release"'

PROBLEM_KINDS = (
    "health: job not Complete; failed: failed test cases (e.g. "
    "kernel-log-clean); uploads: failed uploads; no_results: a test "
    "definition without results; console: kernel splats on the console; "
    "retried: actions that passed only on another attempt (bbb boot), "
    "the job itself is fine."
)


def detail_url(board, flavor, test, round=None):
    """The detail dashboard for one board/flavor/test (flavor None: the
    dashboard's default), same time range; round: the round shown in
    depth (default: the latest)."""
    url = f"/d/{DETAIL_UID}/rt-test-detail?var-board={board}&var-test={test}"
    if flavor:
        url += f"&var-flavor={flavor}"
    if round:
        url += f"&var-round={round}"
    return url + "&${__url_time_range}"


class Dashboard:
    def __init__(self, lava_url):
        self.lava_url = lava_url.rstrip("/")
        self.panels = []
        self.y = 0
        self.pid = 0

    def _id(self):
        self.pid += 1
        return self.pid

    def _target(self, expr, legend="", instant=False, fmt="time_series", ref="A"):
        return {
            "datasource": DS,
            "expr": expr,
            "refId": ref,
            "legendFormat": legend,
            "instant": instant,
            "range": not instant,
            "format": fmt,
        }

    def _panel(self, kind, title, x, w, h, desc="", **extra):
        p = {
            "type": kind,
            "title": title,
            "description": desc,
            "id": self._id(),
            "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
        }
        p.update(extra)
        self.panels.append(p)
        return p

    def job_link(self):
        """A table override: the Job column links to the LAVA job."""
        links = [
            {
                "title": "LAVA job ${__value.raw}",
                "url": f"{self.lava_url}/scheduler/job/${{__value.raw}}",
                "targetBlank": True,
            }
        ]
        return {
            "matcher": {"id": "byName", "options": "Job"},
            "properties": [{"id": "links", "value": links}],
        }

    @staticmethod
    def round_link(detail):
        """A table override: the Round column opens that round of
        detail (board, flavor, test) in the detail dashboard."""
        links = [
            {
                "title": "Round ${__value.raw} in detail",
                "url": detail_url(*detail, round="${__value.raw}"),
            }
        ]
        return {
            "matcher": {"id": "byName", "options": "Round"},
            "properties": [{"id": "links", "value": links}],
        }

    def row(self, title, repeat=None):
        r = {
            "type": "row",
            "title": title,
            "id": self._id(),
            "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y},
            "panels": [],
        }
        if repeat:
            r["repeat"] = repeat
        self.panels.append(r)
        self.y += 1

    def stat(self, title, expr, x, w=6, h=4, steps=None, desc="", unit="none"):
        self._panel(
            "stat",
            title,
            x,
            w,
            h,
            desc,
            targets=[self._target(expr, instant=True)],
            fieldConfig={
                "defaults": {
                    "unit": unit,
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "mode": "absolute",
                        "steps": steps or [{"color": "text", "value": None}],
                    },
                },
                "overrides": [],
            },
            options={
                "reduceOptions": {
                    "calcs": ["lastNotNull"],
                    "fields": "",
                    "values": False,
                },
                "colorMode": "background",
                "graphMode": "none",
                "textMode": "value",
            },
        )

    def table(
        self,
        title,
        expr,
        x,
        w,
        h,
        columns,
        value,
        desc="",
        matrix=None,
        detail=None,
        sort=None,
    ):
        """columns: label -> header; value: header of the value.

        matrix: (row label header, column label header) to pivot the
        table, e.g. one column per stat. detail: (board, flavor, test)
        for the Round column's link into the detail dashboard. sort:
        (header, descending).
        """
        keep = list(columns) + ["Value"]
        rename = {**columns, "Value": value}
        transformations = [
            {"id": "filterFieldsByName", "options": {"include": {"names": keep}}},
            {
                "id": "organize",
                "options": {
                    "indexByName": {n: i for i, n in enumerate(keep)},
                    "renameByName": rename,
                },
            },
        ]
        if matrix:
            transformations.append(
                {
                    "id": "groupingToMatrix",
                    "options": {
                        "rowField": matrix[0],
                        "columnField": matrix[1],
                        "valueField": value,
                    },
                }
            )
        options = {"showHeader": True, "cellHeight": "sm"}
        if sort:
            options["sortBy"] = [{"displayName": sort[0], "desc": sort[1]}]
        overrides = []
        if "round" in columns and detail:
            overrides.append(self.round_link(detail))
        if "job" in columns:
            overrides.append(self.job_link())
            # Job ids are labels (text): sort them as numbers.
            conversion = {"targetField": "Job", "destinationType": "number"}
            transformations.append(
                {"id": "convertFieldType", "options": {"conversions": [conversion]}}
            )
        self._panel(
            "table",
            title,
            x,
            w,
            h,
            desc,
            targets=[self._target(expr, instant=True, fmt="table")],
            transformations=transformations,
            fieldConfig={
                "defaults": {
                    "unit": "µs" if "us" in value else "none",
                    "custom": {"align": "auto", "filterable": True},
                },
                "overrides": overrides,
            },
            options=options,
        )

    def round_trend(
        self,
        title,
        expr,
        series,
        x,
        w,
        h,
        desc="",
        log=True,
        row="round",
        overrides=(),
        **extra,
    ):
        """Grafana's Trend panel: the round on the x axis, a line per
        value of label series. An instant query over the dashboard's
        range gives a row per round and series; the matrix makes a
        column per series, and label row (round, a text) becomes a
        number for the x axis. Test rounds (t3) aren't numbers: release
        only, unless the query makes a number label (by_kind) for row."""
        return self._panel(
            "trend",
            title,
            x,
            w,
            h,
            desc,
            targets=[self._target(expr, instant=True, fmt="table")],
            transformations=[
                {
                    "id": "groupingToMatrix",
                    "options": {
                        "rowField": row,
                        "columnField": series,
                        "valueField": "Value",
                    },
                },
                {
                    "id": "organize",
                    "options": {"renameByName": {f"{row}\\{series}": "Round"}},
                },
                {
                    "id": "convertFieldType",
                    "options": {
                        "conversions": [
                            {"targetField": "Round", "destinationType": "number"}
                        ]
                    },
                },
                {"id": "sortBy", "options": {"sort": [{"field": "Round"}]}},
            ],
            fieldConfig={
                "defaults": {
                    "unit": "µs",
                    "custom": {
                        "drawStyle": "line",
                        "lineWidth": 1,
                        "pointSize": 5,
                        "showPoints": "always",
                        "spanNulls": True,
                        "scaleDistribution": (
                            {"type": "log", "log": 10} if log else {"type": "linear"}
                        ),
                    },
                },
                # The defaults are for the latencies; the x axis is the
                # round: a plain whole number on a linear scale.
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "Round"},
                        "properties": [
                            {"id": "unit", "value": "none"},
                            {"id": "decimals", "value": 0},
                            {
                                "id": "custom.scaleDistribution",
                                "value": {"type": "linear"},
                            },
                        ],
                    },
                    *overrides,
                ],
            },
            options={
                "xField": "Round",
                "legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            **extra,
        )

    def round_bars(self, title, rounds, sel, x, w, h, desc=""):
        """Two rounds side by side: a bar per board, test and workload
        for each."""
        targets = []
        for i, rnd in enumerate(rounds):
            expr = (
                "label_join(max by (board, test, workload) (max_over_time("
                f'srt_latency_us{{stat="max", round="{rnd}", {sel}}}[$__range])), '
                '"key", " ", "board", "test", "workload")'
            )
            targets.append(
                self._target(expr, rnd, instant=True, fmt="table", ref=chr(65 + i))
            )
        return self._panel(
            "barchart",
            title,
            x,
            w,
            h,
            desc,
            targets=targets,
            transformations=[
                {"id": "joinByField", "options": {"byField": "key", "mode": "outer"}},
                {
                    "id": "organize",
                    "options": {
                        "renameByName": {
                            f"Value #{chr(65 + i)}": rnd for i, rnd in enumerate(rounds)
                        },
                        "excludeByName": {"Time": True, "Time 1": True, "Time 2": True},
                    },
                },
            ],
            fieldConfig={"defaults": {"unit": "µs"}, "overrides": []},
            options={
                "xField": "key",
                "orientation": "horizontal",
                "groupWidth": 0.8,
                "barWidth": 0.9,
                "legend": {"displayMode": "list", "placement": "bottom"},
            },
        )

    def buckets(self, title, expr, x, w, h, desc=""):
        """Bar gauge of a histogram (Grafana turns the cumulative
        buckets into counts per bucket with format heatmap)."""
        self._panel(
            "bargauge",
            title,
            x,
            w,
            h,
            desc,
            targets=[self._target(expr, "{{le}}", instant=True, fmt="heatmap")],
            fieldConfig={"defaults": {"unit": "none"}, "overrides": []},
            options={
                "displayMode": "basic",
                "orientation": "horizontal",
                "showUnfilled": True,
                "reduceOptions": {
                    "calcs": ["lastNotNull"],
                    "fields": "",
                    "values": False,
                },
            },
        )


def _round_kind_var():
    """release by default: test rounds only when chosen."""
    return {
        "name": "round_kind",
        "label": "round kind",
        "type": "custom",
        "query": "release,test",
        "options": [
            {"text": v, "value": v, "selected": v == "release"}
            for v in ("release", "test")
        ],
        "current": {"text": "release", "value": "release"},
        "multi": True,
        "includeAll": True,
    }


def _workload_var(sel):
    """All by default, as .*: it also matches samples without a workload
    (Grafana's own All lists the values, which a missing label fails)."""
    v = _var("workload", f"label_values(srt_latency_us{{{sel}}}, workload)")
    v["allValue"] = ".*"
    v["current"] = {"text": "All", "value": "$__all"}
    return v


def _var(name, query, multi=True, include_all=True, sort=1):
    """sort: 1 alphabetical, 4 numerical descending (latest job first)."""
    return {
        "name": name,
        "type": "query",
        "datasource": DS,
        "query": {"query": query, "refId": name},
        "definition": query,
        "refresh": 2,
        "multi": multi,
        "includeAll": include_all,
        "current": {},
        "sort": sort,
    }


def _dashboard(
    uid, title, description, lava_url, panels, variables, links, since="now-90d"
):
    return {
        "uid": uid,
        "title": title,
        "tags": ["rt", "lava"],
        "timezone": "browser",
        "editable": False,
        "refresh": "",
        "time": {"from": since, "to": "now"},
        "schemaVersion": 39,
        "version": 1,
        "description": description + " Generated by `srt-build jobs dashboard` "
        "(srt_build/grafana.py): edit and rerun that, not the JSON.",
        "links": [
            *links,
            {"title": "LAVA", "url": lava_url, "type": "link", "targetBlank": True},
        ],
        "panels": panels,
        "templating": {"list": variables},
        "annotations": {"list": []},
    }


def band(ref):
    """(upper, lower) of the normal range of ref (max latency per round,
    label round): scalars, the median +- BAND_K robust standard
    deviations (1.4826 x MAD), but at least +- BAND_MIN of the median
    and BAND_MIN_US: rounds alike to the microsecond (c2d: 11, 12, 12)
    have a MAD of 0, and a few rounds give a narrow, unsteady MAD. lower
    at least 1 us (log axes)."""
    median = f"quantile(0.5, {ref})"
    sd = f"(1.4826 * quantile(0.5, abs({ref} - scalar({median}))))"
    least = f"scalar(clamp_min({BAND_MIN} * {median}, {BAND_MIN_US}))"
    half = f"clamp_min({BAND_K} * {sd}, {least})"
    return (
        f"scalar({median} + {half})",
        f"scalar(clamp_min({median} - {half}, 1))",
    )


def band_series(ref, value):
    """The band's series for a round trend: upper and lower on every
    round of ref, and outside: the rounds whose value (same labels as
    ref) lies above it, drawn as red points (outside_override). Below
    the band is better, not a problem."""
    upper, lower = band(ref)
    return (
        f' or label_set({ref} * 0 + {upper}, "series", "upper")'
        f' or label_set({ref} * 0 + {lower}, "series", "lower")'
        f' or label_set({value} > {upper}, "series", "outside")'
    )


def build_overview(lava_url):
    """The overview dashboard as a dict."""
    d = Dashboard(lava_url)

    # One row per board, one round trend per test in it.
    d.row("$board", repeat="board")
    by_round = (
        'board="$board", test="$test", flavor=~"$flavor", kernel=~"$kernel", '
        + WL
        + ", "
        + RELEASE
    )
    # the band: of the max over the lines shown (flavors, workloads)
    top = (
        "max by (round) (max_over_time("
        f'srt_latency_us{{stat="max", {by_round}}}[$__range]))'
    )
    p = d.round_trend(
        "$test",
        "label_join(max by (round, flavor, workload) (max_over_time("
        f'srt_latency_us{{stat="max", {by_round}}}[$__range])), '
        '"series", " ", "flavor", "workload")' + band_series(top, top),
        "series",
        0,
        4,
        6,
        overrides=band_overrides() + [outside_override()],
        desc="Max latency of each release round (largest of its jobs and "
        "threads), the round on the x axis, a line per flavor and workload; "
        "log scale. Green: the normal range of the largest of them (median "
        f"+- {BAND_K} x 1.4826 x MAD of the rounds shown, at least +- "
        f"{BAND_MIN:.0%} and {BAND_MIN_US} us), red: a round above it. The "
        "title's link opens the test over time, in detail.",
        repeat="test",
        repeatDirection="h",
        maxPerRow=6,
    )
    p["links"] = [{"title": "Details", "url": detail_url("$board", None, "$test")}]
    d.y += 6

    return _dashboard(
        OVERVIEW_UID,
        "RT tests",
        "PREEMPT_RT test rounds in LAVA, from `srt-build round export`: per "
        "board and test a trend over the release rounds; its link opens the "
        "details.",
        lava_url,
        d.panels,
        [
            _var("board", "label_values(srt_job_ok, board)"),
            _var("flavor", 'label_values(srt_job_ok{board=~"$board"}, flavor)'),
            _var(
                "test",
                'label_values(srt_latency_us{board=~"$board", flavor=~"$flavor"}, '
                "test)",
            ),
            _var(
                "kernel",
                'label_values(srt_job_ok{board=~"$board", flavor=~"$flavor"}, kernel)',
            ),
            _workload_var('board=~"$board", flavor=~"$flavor", test=~"$test"'),
        ],
        LINKS,
        since="now-1y",
    )


# The dashboards link to each other (at the top, next to the selectors).
LINKS = [
    {"title": "RT tests", "url": f"/d/{OVERVIEW_UID}", "type": "link"},
    {"title": "RT test detail", "url": f"/d/{DETAIL_UID}", "type": "link"},
    {"title": "RT rounds compared", "url": f"/d/{COMPARE_UID}", "type": "link"},
    {"title": "RT problems", "url": f"/d/{PROBLEMS_UID}", "type": "link"},
]


def build_problems(lava_url):
    """Problems and numbers over all jobs, as a dict: a dashboard of its
    own, so the overview is the trends only."""
    d = Dashboard(lava_url)
    MAX = (
        'max_over_time(srt_latency_us{stat="max", board=~"$board", '
        'flavor=~"$flavor", kernel=~"$kernel", ' + WL + ", " + KIND + "}[$__range])"
    )

    d.row("Summary")
    d.stat("Jobs", f"count(max_over_time(srt_job_ok{{{JOBS}}}[$__range]))", 0)
    d.stat(
        "Jobs with problems",
        f"count(max_over_time(srt_job_ok{{{JOBS}}}[$__range]) == 0) or vector(0)",
        6,
        steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
        desc="Failed health, failed test cases, failed uploads, definitions "
        "without results or kernel splats on the console (`srt-build jobs "
        "report`). Which ones: the table next to it.",
    )
    d.stat(
        "Worst max latency",
        f"max({MAX})",
        12,
        desc="Largest max latency of any thread of any job selected.",
        unit="µs",
    )
    d.stat(
        "srt-build versions",
        f"count(count by (srt_build) "
        f"(max_over_time(srt_job_info{{{JOBS}}}[$__range])))",
        18,
        steps=[{"color": "green", "value": None}, {"color": "orange", "value": 2}],
        desc="More than one: the jobs were submitted by different srt-build "
        "versions.",
    )
    d.y += 4
    d.table(
        "Jobs with problems",
        f"max by ({BY}, kernel, round, job, kind) "
        f"(max_over_time(srt_job_problems{{{JOBS}}}[$__range])) > 0",
        0,
        24,
        6,
        {
            "board": "Board",
            "flavor": "Flavor",
            "test": "Test",
            "kernel": "Kernel",
            "round": "Round",
            "job": "Job",
            "kind": "Problem",
        },
        "Count",
        desc=PROBLEM_KINDS + " Click a job for LAVA, a round for its test in detail.",
        detail=tuple(f"${{__data.fields.{c}}}" for c in ("Board", "Flavor", "Test")),
        sort=("Job", True),
    )
    d.y += 6

    return _dashboard(
        PROBLEMS_UID,
        "RT problems",
        "PREEMPT_RT test rounds in LAVA: the jobs with problems and a few "
        "numbers over all jobs chosen at the top.",
        lava_url,
        d.panels,
        [
            _var("board", "label_values(srt_job_ok, board)"),
            _var("flavor", 'label_values(srt_job_ok{board=~"$board"}, flavor)'),
            _var(
                "kernel",
                'label_values(srt_job_ok{board=~"$board", flavor=~"$flavor"}, kernel)',
            ),
            _workload_var('board=~"$board", flavor=~"$flavor"'),
            _round_kind_var(),
        ],
        LINKS,
        since="now-1y",
    )


def build_compare(lava_url):
    """Two rounds side by side as a dict: its own dashboard, so the
    round A and B selectors sit above what they choose."""
    d = Dashboard(lava_url)
    d.row("Round $round_a and round $round_b")
    d.round_bars(
        "Round $round_a and $round_b",
        ["$round_a", "$round_b"],
        'flavor=~"$flavor", board=~"$board", test=~"$test", ' + WL,
        0,
        24,
        20,
        desc="Max latency per board, test and workload in each of the two "
        "rounds chosen at the top (round kind: which rounds they offer).",
    )
    d.y += 20
    rounds = "label_values(srt_job_ok{" + ROUNDS + "}, round)"
    kind = _round_kind_var()
    kind["current"] = {"text": "All", "value": "$__all"}
    for o in kind["options"]:
        o["selected"] = False
    return _dashboard(
        COMPARE_UID,
        "RT rounds compared",
        "Two PREEMPT_RT rounds, release or test, side by side: the max "
        "latency per board, test and workload.",
        lava_url,
        d.panels,
        [
            kind,
            {**_var("round_a", rounds, False, False, sort=4), "label": "round A"},
            {**_var("round_b", rounds, False, False, sort=4), "label": "round B"},
            _var("board", "label_values(srt_job_ok, board)"),
            _var("flavor", 'label_values(srt_job_ok{board=~"$board"}, flavor)'),
            _var(
                "test",
                'label_values(srt_latency_us{board=~"$board", flavor=~"$flavor"}, '
                "test)",
            ),
            _workload_var('board=~"$board", flavor=~"$flavor", test=~"$test"'),
        ],
        LINKS,
        since="now-1y",
    )


def by_kind(expr, label):
    """For a round trend of the round kinds chosen: expr has the labels
    round, round_kind and label. Adds n, the round's number (t5: 5) for
    the x axis, and line, label's value, with " (test)" for a test
    round: test rounds are lines of their own, release rounds look as
    before."""
    kt = f'label_join({expr}, "kt", ";", "round_kind", "{label}")'
    line = (
        f'label_replace(label_replace({kt}, "line", "$1", "kt", "release;(.*)"), '
        '"line", "$1 (test)", "kt", "test;(.*)")'
    )
    return f'label_replace({line}, "n", "$1", "round", "t?([0-9]+)")'


# The normal range: the median of the release rounds' max latency +-
# BAND_K robust standard deviations (1.4826 x the median absolute
# deviation, MAD), a band behind the line. Median and MAD: one wild
# round (round 11's 185 ms) barely moves the band, it shows outside.
BAND_K = 3
# The band's least half width: of the median, and in microseconds;
# doc/TUNING.md: only a change beyond about 40 % and 20 us is worth a
# look. With more rounds the MAD alone will do.
BAND_MIN = 0.4
BAND_MIN_US = 20


def band_overrides(color="green"):
    """upper and lower: no lines or points of their own, the area
    between them filled (Grafana's fill below to)."""

    def edge(name, extra=()):
        return {
            "matcher": {"id": "byName", "options": name},
            "properties": [
                {"id": "custom.lineWidth", "value": 0},
                {"id": "custom.showPoints", "value": "never"},
                {
                    "id": "custom.hideFrom",
                    "value": {"legend": True, "tooltip": False, "viz": False},
                },
                {"id": "color", "value": {"mode": "fixed", "fixedColor": color}},
                *extra,
            ],
        }

    return [
        edge(
            "upper",
            [
                {"id": "custom.fillBelowTo", "value": "lower"},
                {"id": "custom.fillOpacity", "value": 20},
            ],
        ),
        edge("lower"),
    ]


def outside_override():
    """The rounds outside the band (series outside, a test round's
    "outside (test)"): big red points, no line."""
    return {
        "matcher": {"id": "byRegexp", "options": "outside.*"},
        "properties": [
            {"id": "custom.drawStyle", "value": "points"},
            {"id": "custom.pointSize", "value": 12},
            {"id": "custom.showPoints", "value": "always"},
            {"id": "custom.spanNulls", "value": False},
            {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}},
        ],
    }


def build_detail(lava_url):
    """The detail dashboard (one board, flavor and test) as a dict: the
    rounds of the chosen kinds side by side, and one round in depth."""
    d = Dashboard(lava_url)
    # The round trends: the rounds of the kinds chosen at the top
    # (release by default); by_kind makes their x axis and lines.
    BYROUND = (
        'board="$board", flavor="$flavor", test="$test", kernel=~"$kernel", '
        + WL
        + ", "
        + ROUNDS
    )
    # The round shown in depth.
    ROUND = ONE + ', round="$round"'
    detail = ("$board", "$flavor", "$test")

    def per_round(stat, by):
        return by_kind(
            f"max by (round, round_kind, {by}) (max_over_time(srt_latency_us"
            f'{{stat="{stat}", {BYROUND}}}[$__range]))',
            by,
        )

    def quantile(q, name):
        return (
            f"label_set(histogram_quantile({q}, sum by (round, round_kind, le) "
            f"(max_over_time(srt_latency_bucket{{{BYROUND}}}[$__range]))), "
            f'"series", "{name}")'
        )

    d.row("By round")
    # The release rounds' max latency, the reference for the band.
    REF = (
        "max by (round, round_kind) (max_over_time(srt_latency_us"
        '{stat="max", board="$board", flavor="$flavor", test="$test", '
        f'kernel=~"$kernel", {WL}, {RELEASE}}}[$__range]))'
    )
    MAX = (
        "max by (round, round_kind) (max_over_time(srt_latency_us"
        f'{{stat="max", {BYROUND}}}[$__range]))'
    )
    d.round_trend(
        "Max latency and normal range",
        by_kind(
            f'label_set({MAX}, "series", "max")' + band_series(REF, MAX),
            "series",
        ),
        "line",
        0,
        24,
        8,
        row="n",
        overrides=band_overrides() + [outside_override()],
        desc="Max latency of each round (all threads and workloads chosen), "
        f"in front of the normal range: the median +- {BAND_K} robust standard "
        "deviations (1.4826 x MAD) of the release rounds shown, at least +- "
        f"{BAND_MIN:.0%} and {BAND_MIN_US} us; one wild round barely moves "
        "it. A round above the band is a red point, worth a look; with few "
        "rounds the band is rough. Log scale.",
    )
    d.y += 8
    d.round_trend(
        "Max latency per thread",
        per_round("max", "thread"),
        "line",
        0,
        12,
        9,
        row="n",
        desc="Max latency of each thread in each round of the kinds chosen at "
        "the top (a test round's lines say (test), its x is its number: t5 at "
        "5). t: thread "
        "(cyclictest: thread index, rtla: CPU), i: rtla's IRQ, u: rtla's "
        "user-space thread. Log scale.",
    )
    d.round_trend(
        "Percentiles (all threads)",
        by_kind(
            " or ".join(
                [
                    quantile(q, n)
                    for q, n in ((0.5, "p50"), (0.99, "p99"), (0.999, "p99.9"))
                ]
                + [
                    "label_set(max by (round, round_kind) (max_over_time("
                    f'srt_latency_us{{stat="max", {BYROUND}}}[$__range])), '
                    '"series", "max")'
                ]
            ),
            "series",
        ),
        "line",
        12,
        12,
        9,
        row="n",
        desc="From the uploaded histograms (cyclictest, rtla), all threads of "
        "a round together; estimated within the bucket (5, 10, 20, 30, 50, 75, "
        "100, 150, 200, 300, 500, 750, 1000, 2000 us). max: the test's own "
        "result. Log scale.",
    )
    d.y += 9
    d.round_trend(
        "Average latency per thread",
        per_round("avg", "thread"),
        "line",
        0,
        12,
        9,
        log=False,
        row="n",
    )
    d.table(
        "Rounds",
        f'max by (round, kernel) (max_over_time(srt_latency_us{{stat="max", '
        f"{ONE}}}[$__range]))",
        12,
        12,
        9,
        {"round": "Round", "kernel": "Kernel"},
        "Max (us)",
        desc="Max latency of each round, release and test rounds as chosen at "
        "the top. Click a round to show it below.",
        detail=detail,
        sort=("Round", True),
    )
    d.y += 9

    d.row("Round $round")
    d.buckets(
        "Histogram of round $round",
        f"sum by (le) (max_over_time(srt_latency_bucket{{{ROUND}}}[$__range]))",
        0,
        12,
        10,
        desc="Samples per latency bucket, all threads (and with workload All, "
        "all workloads) of the round together. Pick the round at the top or in "
        "the Rounds table (latest by default).",
    )
    d.table(
        "Threads of round $round",
        f"max by (thread, stat) (max_over_time(srt_latency_us{{{ROUND}}}[$__range]))",
        12,
        12,
        10,
        {"thread": "Thread", "stat": "Stat"},
        "Latency (us)",
        matrix=("Thread", "Stat"),
    )
    d.y += 10

    d.row("Jobs and kernels")
    d.table(
        "Jobs",
        "max by (round, job, workload, kernel) (max_over_time(srt_latency_us"
        f'{{stat="max", {ONE}}}[$__range]))',
        0,
        10,
        10,
        {"round": "Round", "job": "Job", "workload": "Workload", "kernel": "Kernel"},
        "Max (us)",
        desc="Max latency of each job. Click a job for LAVA, a round to show it "
        "above.",
        detail=detail,
        sort=("Job", True),
    )
    # A combined job's job-level series carry the job's test (rt-tests),
    # not this one: take the problems of the jobs with results for it.
    jobs = 'board="$board", flavor="$flavor", kernel=~"$kernel", ' + KIND
    d.table(
        "Problems",
        f"(max by (round, job, kernel, kind) "
        f"(max_over_time(srt_job_problems{{{jobs}}}[$__range])) > 0) "
        f"and on (job) count by (job) "
        f"(max_over_time(srt_latency_us{{{ONE}}}[$__range]))",
        10,
        8,
        10,
        {"round": "Round", "job": "Job", "kernel": "Kernel", "kind": "Problem"},
        "Count",
        desc=PROBLEM_KINDS,
        detail=detail,
        sort=("Job", True),
    )
    d.table(
        "Kernels",
        f'max by (kernel) (max_over_time(srt_latency_us{{stat="max", '
        f"{ONE}}}[$__range]))",
        18,
        6,
        10,
        {"kernel": "Kernel"},
        "Max (us)",
        desc="Largest max latency per kernel.",
    )
    d.y += 10

    sel = 'board="$board", flavor="$flavor", test="$test"'
    return _dashboard(
        DETAIL_UID,
        "RT test detail",
        "One board, flavor and test of the PREEMPT_RT test rounds in LAVA: the "
        "release rounds side by side, one round in depth.",
        lava_url,
        d.panels,
        [
            _var("board", "label_values(srt_job_ok, board)", False, False),
            _var(
                "flavor",
                'label_values(srt_latency_us{board="$board"}, flavor)',
                False,
                False,
            ),
            _var(
                "test",
                'label_values(srt_latency_us{board="$board", flavor="$flavor"}, '
                "test)",
                False,
                False,
            ),
            _var("kernel", f"label_values(srt_latency_us{{{sel}}}, kernel)"),
            _workload_var(sel),
            _round_kind_var(),
            _var(
                "round",
                f"label_values(srt_latency_us{{{sel}, {ROUNDS}}}, round)",
                False,
                False,
                sort=4,
            ),
        ],
        LINKS,
        since="now-1y",
    )


DASHBOARDS = {
    "rt-tests.json": build_overview,
    "rt-test-detail.json": build_detail,
    "rt-rounds-compared.json": build_compare,
    "rt-problems.json": build_problems,
}


def build_all(lava_url):
    """{file name: dashboard}."""
    return {name: build(lava_url) for name, build in DASHBOARDS.items()}


def queries(dashboard):
    """Every query of the dashboard, to try them against VictoriaMetrics."""
    for p in dashboard["panels"]:
        for t in p.get("targets", []):
            yield {"panel": p["title"], "expr": t["expr"]}
    for v in dashboard["templating"]["list"]:
        if v["type"] == "query":
            yield {"variable": v["name"], "expr": v["definition"]}
