"""round compare - two rounds side by side, from the archive.

  srt-build round compare 12 13
  srt-build round compare 13 t2

One line per board, flavor, test and workload: the max latency in
each round and the change; then the jobs with problems in either.
Jobs a rerun replaced are left out, as everywhere.
"""

from ..archive import ArchiveApi, counted_jobs, load_round, round_dir
from ..archive import archive_path, parse_round
from ..metrics import definition_workloads, job_labels
from ..report import summarize_job


def add_parsers(sub):
    p = sub.add_parser("compare", help="two rounds side by side")
    p.add_argument("a", help="a round: 12 (release), t3 (test)")
    p.add_argument("b", help="the other round")
    p.set_defaults(func=cmd_round_compare)


def round_results(archive, rid):
    """({(board, flavor, test, workload): max latency}, [problem lines])."""
    info = load_round(archive, rid)
    a = ArchiveApi(round_dir(archive, rid))
    out, problems = {}, []
    for jid in counted_jobs(info):
        if not a.has(jid):
            problems.append(f"job {jid}: not in the archive")
            continue
        job, tests = a.job(jid), a.tests(jid)
        s = summarize_job(job, tests, a.suites(jid), a.log(jid))
        labels = job_labels(job, s)
        workloads = definition_workloads(job)
        board, flavor = labels["board"], labels["flavor"]
        if s.per_test:
            for name, lat in s.per_test:
                out[(board, flavor, name, workloads.get(name, ""))] = lat
        else:
            wl = next(iter(workloads.values())) if len(workloads) == 1 else ""
            out[(board, flavor, labels["test"], wl)] = s.max_latency
        if s.problems():
            problems.append(f"job {jid} {board} {labels['test']}: "
                            + "; ".join(s.problems()))  # fmt: skip
    return out, problems


def _fmt(v):
    return "-" if v is None else f"{v:.0f}"


def compare_lines(ra, rb, a, b):
    rows = [["board", "flavor", "test", "workload", a, b, "change"]]
    for key in sorted(set(ra) | set(rb)):
        va, vb = ra.get(key), rb.get(key)
        change = ""
        if va and vb is not None:
            change = f"{(vb - va) / va * 100:+.0f}%"
        rows.append([*key, _fmt(va), _fmt(vb), change])
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def cmd_round_compare(args, system_config, machine_config):
    archive = archive_path(system_config)
    a, b = parse_round(args.a), parse_round(args.b)
    ra, pa = round_results(archive, a)
    rb, pb = round_results(archive, b)
    print("\n".join(compare_lines(ra, rb, a, b)))
    for rid, problems in ((a, pa), (b, pb)):
        if problems:
            print(f"\nproblems in round {rid}:")
            for line in problems:
                print("  " + line)
