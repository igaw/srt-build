"""The rt-tests Grafana dashboards, for the samples of `jobs export`.

`srt-build jobs dashboard DIR` writes them; homelab provisions the
files (grafana_dashboard_files on monitor). Edit this and rerun, not
the JSON.

  rt-tests.json        "RT tests": the overview. One row per board, in
                       it one trend per test (max latency of each job,
                       a line per flavor), and what needs a look
                       (problems). A click on a trend opens:
  rt-test-detail.json  "RT test detail": one board, flavor and test.
                       Trends per thread and percentiles, the histograms
                       over time, one job's histogram and threads, the
                       jobs and kernels.

The overview also lines the rounds up (`round export` labels the
samples with round and round_kind): per board and test a Trend panel
with the round on the x axis, and two rounds side by side. Grafana's
Trend panel needs Grafana 10 or later. The round_kind variable
(release by default) keeps test rounds out unless chosen; samples
without the label (`jobs export`) always show in the time trends.

Every job is a handful of samples at the job's end time, not a
continuous series: trends take each job's value per interval
(last_over_time over $__interval) and join the points; tables take the
largest value over the dashboard's time range.
"""

DS = {"type": "prometheus", "uid": "victoriametrics"}
OVERVIEW_UID = "rt-tests"
DETAIL_UID = "rt-test-detail"

# Samples of the chosen round kinds, and those without round (jobs
# export): "" matches a missing label.
KIND = 'round_kind=~"$round_kind|"'
# The overview's variables, as label matchers.
SEL = 'board=~"$board", flavor=~"$flavor", test=~"$test", kernel=~"$kernel", ' + KIND
# For the job counts and problems: all tests, also those without
# latencies (smoke-tests, isolcpus, pi-stress), which $test leaves out.
JOBS = 'board=~"$board", flavor=~"$flavor", kernel=~"$kernel", ' + KIND
BY = "board, flavor, test"
# The detail dashboard's: one board, flavor and test.
ONE = 'board="$board", flavor="$flavor", test="$test", kernel=~"$kernel", ' + KIND
# Round samples only, of the chosen kinds.
ROUNDS = 'round_kind=~"$round_kind"'

PROBLEM_KINDS = (
    "health: job not Complete; failed: failed test cases (e.g. "
    "kernel-log-clean); uploads: failed uploads; no_results: a test "
    "definition without results; console: kernel splats on the console; "
    "retried: actions that passed only on another attempt (bbb boot), "
    "the job itself is fine."
)


def detail_url(board, flavor, test, job=None):
    """The detail dashboard for one board/flavor/test (flavor None: the
    dashboard's default), same time range."""
    url = f"/d/{DETAIL_UID}/rt-test-detail?var-board={board}&var-test={test}"
    if flavor:
        url += f"&var-flavor={flavor}"
    if job:
        url += f"&var-job={job}"
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

    def job_link(self, detail=None):
        """A table override: the Job column links to the LAVA job and,
        with detail (board, flavor, test), to the job in the detail
        dashboard."""
        links = [
            {
                "title": "LAVA job ${__value.raw}",
                "url": f"{self.lava_url}/scheduler/job/${{__value.raw}}",
                "targetBlank": True,
            }
        ]
        if detail:
            links.append(
                {
                    "title": "Job ${__value.raw} in detail",
                    "url": detail_url(*detail, job="${__value.raw}"),
                }
            )
        return {
            "matcher": {"id": "byName", "options": "Job"},
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
        for the Job column's link into the detail dashboard. sort:
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
        if "job" in columns:
            overrides.append(self.job_link(detail))
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

    def trend(self, title, targets, x, w, h, desc="", links=None, log=True, **extra):
        """A time series of jobs: a point per job, joined by lines
        (spanNulls: the time between rounds has no samples). A log axis
        by default, so one outlier doesn't flatten everything else."""
        custom = {
            "drawStyle": "line",
            "lineWidth": 1,
            "pointSize": 5,
            "showPoints": "always",
            "spanNulls": True,
        }
        if log:
            custom["scaleDistribution"] = {"type": "log", "log": 10}
        return self._panel(
            "timeseries",
            title,
            x,
            w,
            h,
            desc,
            targets=[
                self._target(expr, legend, ref=chr(ord("A") + i))
                for i, (expr, legend) in enumerate(targets)
            ],
            fieldConfig={
                "defaults": {"unit": "µs", "custom": custom, "links": links or []},
                "overrides": [],
            },
            options={
                "legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            **extra,
        )

    def round_trend(self, title, expr, series, x, w, h, desc="", **extra):
        """Grafana's Trend panel: the round on the x axis, a line per
        value of label series. An instant query over the dashboard's
        range gives a row per round and series; the matrix makes a
        column per series, and round (a label, text) becomes a number
        for the x axis. Test rounds (t3) aren't numbers: release only."""
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
                        "rowField": "round",
                        "columnField": series,
                        "valueField": "Value",
                    },
                },
                {
                    "id": "organize",
                    "options": {"renameByName": {f"round\\{series}": "Round"}},
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
                        "scaleDistribution": {"type": "log", "log": 10},
                    },
                },
                "overrides": [],
            },
            options={
                "xField": "Round",
                "legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            **extra,
        )

    def round_bars(self, title, rounds, sel, x, w, h, desc=""):
        """Two rounds side by side: a bar per board and test for each."""
        targets = []
        for i, rnd in enumerate(rounds):
            expr = (
                "label_join(max by (board, test) (max_over_time(srt_latency_us"
                f'{{stat="max", round="{rnd}", {sel}}}[$__range])), '
                '"key", " ", "board", "test")'
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

    def heatmap(self, title, expr, x, w, h, desc=""):
        """The histograms of the jobs over time: a column per job, a
        cell per bucket (le), colored by its number of samples."""
        self._panel(
            "heatmap",
            title,
            x,
            w,
            h,
            desc,
            targets=[self._target(expr, "{{le}}", fmt="heatmap")],
            options={
                "calculate": False,
                "yAxis": {"axisPlacement": "left", "unit": "µs"},
                "rowsFrame": {"layout": "auto"},
                "color": {
                    "mode": "scheme",
                    "scheme": "Oranges",
                    "scale": "exponential",
                    "exponent": 0.3,
                    "fill": "dark-orange",
                },
                "cellGap": 1,
                "tooltip": {"mode": "single", "yHistogram": True},
                "legend": {"show": True},
            },
            fieldConfig={"defaults": {}, "overrides": []},
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


def _dashboard(uid, title, description, lava_url, panels, variables, links):
    return {
        "uid": uid,
        "title": title,
        "tags": ["rt", "lava"],
        "timezone": "browser",
        "editable": False,
        "refresh": "",
        "time": {"from": "now-90d", "to": "now"},
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


def _latency(stat, sel, window="$__interval"):
    return f'last_over_time(srt_latency_us{{stat="{stat}", {sel}}}[{window}])'


def build_overview(lava_url):
    """The overview dashboard as a dict."""
    d = Dashboard(lava_url)
    MAX = f'max_over_time(srt_latency_us{{stat="max", {SEL}}}[$__range])'

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
        f"max by ({BY}, kernel, job, kind) "
        f"(max_over_time(srt_job_problems{{{JOBS}}}[$__range])) > 0",
        0,
        24,
        6,
        {
            "board": "Board",
            "flavor": "Flavor",
            "test": "Test",
            "kernel": "Kernel",
            "job": "Job",
            "kind": "Problem",
        },
        "Count",
        desc=PROBLEM_KINDS + " Click a job for LAVA or its test in detail.",
        detail=tuple(f"${{__data.fields.{c}}}" for c in ("Board", "Flavor", "Test")),
        sort=("Job", True),
    )
    d.y += 6

    # One row per board, one trend per test in it.
    d.row("$board", repeat="board")
    one_test = (
        'board="$board", test="$test", flavor=~"$flavor", kernel=~"$kernel", ' + KIND
    )
    p = d.trend(
        "$test",
        [(f"max by (flavor) ({_latency('max', one_test)})", "{{flavor}}")],
        0,
        4,
        6,
        desc="Max latency of each job (largest of its threads), a line per "
        "flavor; log scale. Click a point or the title's link for the details.",
        links=[
            {
                "title": "$test on $board, ${__field.labels.flavor}, in detail",
                "url": detail_url("$board", "${__field.labels.flavor}", "$test"),
            }
        ],
        repeat="test",
        repeatDirection="h",
        maxPerRow=6,
    )
    p["links"] = [{"title": "Details", "url": detail_url("$board", None, "$test")}]
    d.y += 6
    by_round = (
        'board="$board", test="$test", flavor=~"$flavor", kernel=~"$kernel", ' + ROUNDS
    )
    d.round_trend(
        "$test by round",
        f'max by (round, flavor) (max_over_time(srt_latency_us{{stat="max", '
        f"{by_round}}}[$__range]))",
        "flavor",
        0,
        4,
        6,
        desc="Max latency of each round (largest of its jobs and threads), the "
        "round on the x axis, a line per flavor; log scale. Release rounds.",
        repeat="test",
        repeatDirection="h",
        maxPerRow=6,
    )
    d.y += 6

    d.row("Two rounds")
    d.round_bars(
        "Round $round_a and $round_b",
        ["$round_a", "$round_b"],
        'flavor=~"$flavor", board=~"$board", test=~"$test", ' + ROUNDS,
        0,
        24,
        12,
        desc="Max latency per board and test in each of the two rounds chosen "
        "at the top.",
    )
    d.y += 12

    return _dashboard(
        OVERVIEW_UID,
        "RT tests",
        "PREEMPT_RT test rounds in LAVA, from `srt-build jobs export`: a trend "
        "per board and test; click one for the details.",
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
            _round_kind_var(),
            _var(
                "round_a",
                "label_values(srt_job_ok{" + ROUNDS + "}, round)",
                False,
                False,
                sort=4,
            ),
            _var(
                "round_b",
                "label_values(srt_job_ok{" + ROUNDS + "}, round)",
                False,
                False,
                sort=4,
            ),
        ],
        [{"title": "RT test detail", "url": f"/d/{DETAIL_UID}", "type": "link"}],
    )


def build_detail(lava_url):
    """The detail dashboard (one board, flavor and test) as a dict."""
    d = Dashboard(lava_url)
    BUCKET = f"srt_latency_bucket{{{ONE}}}"
    JOB = ONE + ', job="$job"'
    detail = ("$board", "$flavor", "$test")

    d.row("Trends")
    d.trend(
        "Max latency per thread",
        [(f"max by (thread) ({_latency('max', ONE)})", "{{thread}}")],
        0,
        12,
        9,
        desc="Each point is a job. t: thread (cyclictest: thread index, rtla: "
        "CPU), i: rtla's IRQ, u: rtla's user-space thread. Log scale.",
    )
    d.trend(
        "Percentiles (all threads)",
        [
            (
                f"histogram_quantile({q}, sum by (le) "
                f"(last_over_time({BUCKET}[$__interval])))",
                name,
            )
            for q, name in ((0.5, "p50"), (0.99, "p99"), (0.999, "p99.9"))
        ]
        + [(f"max({_latency('max', ONE)})", "max")],
        12,
        12,
        9,
        desc="From the uploaded histograms (cyclictest, rtla), all threads of "
        "a job together; estimated within the bucket (5, 10, 20, 30, 50, 75, "
        "100, 150, 200, 300, 500, 750, 1000, 2000 us). max: the test's own "
        "result. Log scale.",
    )
    d.y += 9
    d.heatmap(
        "Histograms over time",
        f"sum by (le) (last_over_time({BUCKET}[$__interval]))",
        0,
        12,
        9,
        desc="A column per job: how many samples fell into each latency "
        "bucket, all threads together. A shift up is a slower kernel or board.",
    )
    d.trend(
        "Average latency per thread",
        [(f"max by (thread) ({_latency('avg', ONE)})", "{{thread}}")],
        12,
        12,
        9,
        log=False,
    )
    d.y += 9

    d.row("Job $job")
    d.buckets(
        "Histogram of job $job",
        f"sum by (le) (max_over_time(srt_latency_bucket{{{JOB}}}[$__range]))",
        0,
        12,
        10,
        desc="Samples per latency bucket, all threads together. Pick the job "
        "at the top or in the job list below (latest by default).",
    )
    d.table(
        "Threads of job $job",
        f"max by (thread, stat) (max_over_time(srt_latency_us{{{JOB}}}[$__range]))",
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
        f'max by (job, kernel) (max_over_time(srt_latency_us{{stat="max", '
        f"{ONE}}}[$__range]))",
        0,
        10,
        10,
        {"job": "Job", "kernel": "Kernel"},
        "Max (us)",
        desc="Max latency of each job. Click a job for LAVA or to show it above.",
        detail=detail,
        sort=("Job", True),
    )
    d.table(
        "Problems",
        f"max by (kernel, job, kind) "
        f"(max_over_time(srt_job_problems{{{ONE}}}[$__range])) > 0",
        10,
        8,
        10,
        {"job": "Job", "kernel": "Kernel", "kind": "Problem"},
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
        "One board, flavor and test of the PREEMPT_RT test rounds in LAVA.",
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
            _var("kernel", f"label_values(srt_job_ok{{{sel}}}, kernel)"),
            _round_kind_var(),
            _var(
                "job",
                f'label_values(srt_job_ok{{{sel}, kernel=~"$kernel"}}, job)',
                False,
                False,
                sort=4,
            ),
        ],
        [{"title": "RT tests", "url": f"/d/{OVERVIEW_UID}", "type": "link"}],
    )


DASHBOARDS = {"rt-tests.json": build_overview, "rt-test-detail.json": build_detail}


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
