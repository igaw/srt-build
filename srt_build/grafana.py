"""The rt-tests Grafana dashboard, for the samples of `jobs export`.

`srt-build jobs dashboard rt-tests.json` writes it; homelab provisions
the file (grafana_dashboard_files on monitor). Edit this and rerun, not
the JSON.

Every job is a handful of samples at the job's end time, not a
continuous series, so the panels either take the largest value over
the dashboard's time range (tables, per kernel) or show each job as a
point (trends).
"""

DS = {"type": "prometheus", "uid": "victoriametrics"}
# The dashboard's variables, as label matchers.
SEL = 'board=~"$board", flavor=~"$flavor", test=~"$test"'
SEL_K = SEL + ', kernel=~"$kernel"'
BY = "board, flavor, test"


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

    def _job_link(self):
        """A table override: the job column links to the LAVA job."""
        return {
            "matcher": {"id": "byName", "options": "Job"},
            "properties": [
                {
                    "id": "links",
                    "value": [
                        {
                            "title": "LAVA job ${__value.raw}",
                            "url": f"{self.lava_url}/scheduler/job/${{__value.raw}}",
                            "targetBlank": True,
                        }
                    ],
                }
            ],
        }

    def row(self, title):
        self.panels.append(
            {
                "type": "row",
                "title": title,
                "id": self._id(),
                "collapsed": False,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y},
                "panels": [],
            }
        )
        self.y += 1

    def stat(self, title, expr, x, w=6, h=4, steps=None, desc=""):
        self.panels.append(
            {
                "type": "stat",
                "title": title,
                "description": desc,
                "id": self._id(),
                "datasource": DS,
                "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
                "targets": [self._target(expr, instant=True)],
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "mode": "absolute",
                            "steps": steps or [{"color": "text", "value": None}],
                        },
                    },
                    "overrides": [],
                },
                "options": {
                    "reduceOptions": {
                        "calcs": ["lastNotNull"],
                        "fields": "",
                        "values": False,
                    },
                    "colorMode": "background",
                    "graphMode": "none",
                    "textMode": "value",
                },
            }
        )

    def table(self, title, expr, x, w, h, columns, value, desc="", matrix=None):
        """columns: label -> header; value: header of the value.

        matrix: (row label header, column label header) to pivot the
        table, e.g. one column per kernel.
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
        self.panels.append(
            {
                "type": "table",
                "title": title,
                "description": desc,
                "id": self._id(),
                "datasource": DS,
                "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
                "targets": [self._target(expr, instant=True, fmt="table")],
                "transformations": transformations,
                "fieldConfig": {
                    "defaults": {
                        "unit": "µs" if "us" in value else "none",
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [self._job_link()],
                },
                "options": {"showHeader": True, "cellHeight": "sm"},
            }
        )

    def points(self, title, targets, x, w, h, unit="µs", desc=""):
        """A time series with one point per job (no lines: a gap between
        rounds is no measurement, not a flat latency)."""
        self.panels.append(
            {
                "type": "timeseries",
                "title": title,
                "description": desc,
                "id": self._id(),
                "datasource": DS,
                "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
                "targets": [
                    self._target(expr, legend, ref=chr(ord("A") + i))
                    for i, (expr, legend) in enumerate(targets)
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": unit,
                        "custom": {
                            "drawStyle": "points",
                            "pointSize": 6,
                            "showPoints": "always",
                        },
                    },
                    "overrides": [],
                },
                "options": {
                    "legend": {"displayMode": "table", "placement": "right"},
                    "tooltip": {"mode": "multi", "sort": "desc"},
                },
            }
        )

    def buckets(self, title, expr, x, w, h, desc=""):
        """Bar gauge of a histogram (Grafana turns the cumulative
        buckets into counts per bucket with format heatmap)."""
        self.panels.append(
            {
                "type": "bargauge",
                "title": title,
                "description": desc,
                "id": self._id(),
                "datasource": DS,
                "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
                "targets": [self._target(expr, "{{le}}", instant=True, fmt="heatmap")],
                "fieldConfig": {"defaults": {"unit": "none"}, "overrides": []},
                "options": {
                    "displayMode": "basic",
                    "orientation": "horizontal",
                    "showUnfilled": True,
                    "reduceOptions": {
                        "calcs": ["lastNotNull"],
                        "fields": "",
                        "values": False,
                    },
                },
            }
        )


def _var(name, query, multi=True, include_all=True):
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
        "sort": 1,
    }


def build(lava_url):
    """The dashboard as a dict."""
    d = Dashboard(lava_url)
    MAX = f'max_over_time(srt_latency_us{{stat="max", {SEL_K}}}[$__range])'
    BUCKET = f"srt_latency_bucket{{{SEL_K}}}"

    d.row("Round")
    d.stat(
        "Jobs",
        f"count(max_over_time(srt_job_ok{{{SEL_K}}}[$__range]))",
        0,
    )
    d.stat(
        "Jobs with problems",
        f"count(max_over_time(srt_job_ok{{{SEL_K}}}[$__range]) == 0) or vector(0)",
        6,
        steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
        desc="Failed health, failed test cases, failed uploads, definitions "
        "without results or kernel splats on the console (`srt-build jobs report`).",
    )
    d.stat(
        "Worst max latency",
        f"max({MAX})",
        12,
        desc="Largest max latency of any thread of any job selected.",
    )
    d.stat(
        "srt-build versions",
        f"count(count by (srt_build) "
        f"(max_over_time(srt_job_info{{{SEL_K}}}[$__range])))",
        18,
        steps=[{"color": "green", "value": None}, {"color": "orange", "value": 2}],
        desc="More than one: the jobs were submitted by different srt-build "
        "versions (see the table below).",
    )
    d.y += 4

    d.row("Kernels compared")
    d.table(
        "Max latency per kernel",
        f'label_join(max by ({BY}, kernel) ({MAX}), "what", " ", '
        '"board", "flavor", "test")',
        0,
        24,
        14,
        {"what": "Board flavor test", "kernel": "Kernel"},
        "Max (us)",
        desc="Largest max latency over all threads, per kernel (columns). "
        "Select kernels at the top to compare releases.",
        matrix=("Board flavor test", "Kernel"),
    )
    d.y += 14

    d.row("Trends")
    d.points(
        "Max latency",
        [
            (
                f'max by ({BY}) (last_over_time(srt_latency_us{{stat="max", {SEL}}}'
                f"[$__interval]))",
                "{{board}} {{flavor}} {{test}}",
            )
        ],
        0,
        12,
        10,
        desc="Each point is a job: the largest max latency of its threads.",
    )
    d.points(
        "p99.9 latency",
        [
            (
                f"histogram_quantile(0.999, sum by ({BY}, le) "
                f"(last_over_time(srt_latency_bucket{{{SEL}}}[$__interval])))",
                "{{board}} {{flavor}} {{test}}",
            )
        ],
        0 + 12,
        12,
        10,
        desc="From the uploaded histograms (cyclictest, rtla), all threads "
        "of a job together; estimated within the bucket "
        "(5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 2000 us).",
    )
    d.y += 10
    d.points(
        "Average latency",
        [
            (
                f'avg by ({BY}) (last_over_time(srt_latency_us{{stat="avg", {SEL}}}'
                f"[$__interval]))",
                "{{board}} {{flavor}} {{test}}",
            )
        ],
        0,
        24,
        8,
    )
    d.y += 8

    d.row("Distribution")
    d.buckets(
        "Histogram of the selected jobs",
        f"sum by (le) (max_over_time({BUCKET}[$__range]))",
        0,
        12,
        10,
        desc="Samples per latency bucket, all threads of all jobs selected "
        "(narrow it down with board, flavor, test and kernel).",
    )
    d.table(
        "Max latency per thread",
        f"max by ({BY}, kernel, job, thread) ({MAX})",
        12,
        12,
        10,
        {
            "board": "Board",
            "flavor": "Flavor",
            "test": "Test",
            "kernel": "Kernel",
            "job": "Job",
            "thread": "Thread",
        },
        "Max (us)",
        desc="t: thread (cyclictest: thread index, rtla: CPU), i: rtla's IRQ, "
        "u: rtla's user-space thread.",
    )
    d.y += 10

    d.row("Problems")
    d.table(
        "Jobs with problems",
        f"max by ({BY}, kernel, job, kind) "
        f"(max_over_time(srt_job_problems{{{SEL_K}}}[$__range])) > 0",
        0,
        16,
        9,
        {
            "board": "Board",
            "flavor": "Flavor",
            "test": "Test",
            "kernel": "Kernel",
            "job": "Job",
            "kind": "Problem",
        },
        "Count",
        desc="health: job not Complete; failed: failed test cases (e.g. "
        "kernel-log-clean); uploads: failed uploads; no_results: a test "
        "definition without results; console: kernel splats on the console; "
        "retried: actions that passed only on another attempt (bbb boot), "
        "the job itself is fine.",
    )
    d.table(
        "srt-build versions",
        f"count by (kernel, srt_build) "
        f"(max_over_time(srt_job_info{{{SEL_K}}}[$__range]))",
        16,
        8,
        9,
        {"kernel": "Kernel", "srt_build": "srt-build"},
        "Jobs",
        desc="Which srt-build version submitted the jobs ('unknown': before "
        "the jobs said so).",
    )
    d.y += 9

    return {
        "uid": "rt-tests",
        "title": "RT tests",
        "tags": ["rt", "lava"],
        "timezone": "browser",
        "editable": False,
        "refresh": "",
        "time": {"from": "now-90d", "to": "now"},
        "schemaVersion": 39,
        "version": 1,
        "description": "PREEMPT_RT test rounds in LAVA, from `srt-build jobs "
        "export`. Generated by `srt-build jobs dashboard` (srt_build/grafana.py): "
        "edit and rerun that, not the JSON.",
        "links": [
            {
                "title": "LAVA",
                "url": lava_url,
                "type": "link",
                "targetBlank": True,
            }
        ],
        "panels": d.panels,
        "templating": {
            "list": [
                _var("board", "label_values(srt_job_ok, board)"),
                _var("flavor", 'label_values(srt_job_ok{board=~"$board"}, flavor)'),
                _var(
                    "test",
                    'label_values(srt_job_ok{board=~"$board", '
                    'flavor=~"$flavor"}, test)',
                ),
                _var(
                    "kernel",
                    'label_values(srt_job_ok{board=~"$board", flavor=~"$flavor", '
                    'test=~"$test"}, kernel)',
                ),
            ]
        },
        "annotations": {"list": []},
    }


def queries(dashboard):
    """Every query of the dashboard, to try them against VictoriaMetrics."""
    for p in dashboard["panels"]:
        for t in p.get("targets", []):
            yield {"panel": p["title"], "expr": t["expr"]}
    for v in dashboard["templating"]["list"]:
        yield {"variable": v["name"], "expr": v["definition"]}
