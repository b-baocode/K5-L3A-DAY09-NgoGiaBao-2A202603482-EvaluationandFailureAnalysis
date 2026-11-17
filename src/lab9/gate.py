"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    problems += _report_problems("PR", pr, graded, spec)
    problems += _report_problems("baseline", base, graded, spec)

    # Same (item, seed) grid as the baseline: no cherry-picked seeds, no dropped or swapped items.
    pr_keys = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])}
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])}
    if pr_keys != base_keys:
        miss = sorted(base_keys - pr_keys, key=str)
        extra = sorted(pr_keys - base_keys, key=str)
        problems.append(f"(item, seed) set differs from baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")
    pm, bm = pr.get("manifest", {}), base.get("manifest", {})
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"manifest seeds {pm.get('seeds')} != baseline seeds {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} != baseline items {bm.get('items')}")

    # Slice tags come from labels, so they must not move between runs on the same eval set.
    pt, bt = _slice_tags(pr), _slice_tags(base)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags differ from baseline for {len(relabelled)} item(s): {relabelled[:5]}")
    unstable = sorted(i for i, t in pt.items() if len(t) > 1)
    if unstable:
        problems.append(f"inconsistent slice tags across seeds for item(s): {unstable[:5]}")

    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _slice_tags(rep: dict) -> dict:
    out: dict = {}
    for r in rep.get("rows", []):
        out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    return out


def _is_bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(who: str, rep: dict, graded: list[str], spec: dict) -> list[str]:
    """Structural checks on one report: the grid, crashed graders, NaN, and metrics that do not
    follow from the rows (hand-edited, or aggregated over a different row set)."""
    problems: list[str] = []
    rows, man = rep.get("rows") or [], rep.get("manifest") or {}
    for k, v in (rep.get("metrics") or {}).items():
        if _is_bad_number(v):
            problems.append(f"{who} metric {k} is {v} (NaN/inf hides missing data)")
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{who} has {len(rows)} rows, manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seen: set = set()
    dups = sorted({k for k in keys if k in seen or seen.add(k)}, key=str)
    if dups:
        problems.append(f"{who} has duplicated (item, seed) rows: {dups[:3]}")
    if rep.get("evaluator_failures"):
        problems.append(f"{who} has {len(rep['evaluator_failures'])} evaluator failure(s): "
                        f"{rep['evaluator_failures'][0]}")
    for m in graded:
        missing = [k for r, k in zip(rows, keys) if r.get(m) is None]
        if missing:
            problems.append(f"{who} metric {m}: {len(missing)} row(s) without a grade, e.g. {missing[0]}")
        odd = [k for r, k in zip(rows, keys) if r.get(m) is not None and not isinstance(r.get(m), bool)]
        if odd:
            problems.append(f"{who} metric {m}: non-boolean grade in {len(odd)} row(s), e.g. {odd[0]}")
    # The headline numbers must be exactly what the rows say (catches hand-edited metrics).
    present = [m for m in graded if rows and all(m in r for r in rows)]
    if present:
        has_cost = all("cost" in r for r in rows)
        safe_rows = [{**r, "cost": float(r.get("cost") or 0.0)} for r in rows]
        try:
            again = aggregate(safe_rows, present, k_values=spec.get("pass_k", []))
        except Exception as e:  # noqa: BLE001 - rows we cannot re-aggregate are untrustworthy
            problems.append(f"{who} rows cannot be re-aggregated: {e!r}")
            again = {}
        for k, v in (rep.get("metrics") or {}).items():
            if k not in again or (k == "cost_per_success" and not has_cost) or _is_bad_number(v):
                continue
            w = again[k]
            if isinstance(v, bool) or isinstance(w, bool):
                v, w = (int(v) if isinstance(v, bool) else v), (int(w) if isinstance(w, bool) else w)
            if (v is None) != (w is None):
                problems.append(f"{who} metrics {k}={v} but rows give {w}")
            elif isinstance(v, (int, float)) and isinstance(w, (int, float)) and abs(v - w) > 1e-6:
                problems.append(f"{who} metrics {k}={v} but rows give {w}")
    return problems


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    if "max" in base_th and ("max" not in th or th["max"] > base_th["max"]):
        out.append(f"max {base_th['max']} -> {th.get('max')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"min {base_th['min']} -> {th.get('min')}")
    if "max_increase" in base_th and ("max_increase" not in th or th["max_increase"] > base_th["max_increase"]):
        out.append(f"max_increase {base_th['max_increase']} -> {th.get('max_increase')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version: thresholds may only get stricter. A new eval-set version starts a
    new baseline, so the ratchet restarts there."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if spec.get(key) != base_spec.get(key):
            problems.append(f"ratchet: {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r}")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        problems.append(f"ratchet: seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    conf = (spec.get("bootstrap") or {}).get("confidence", 0.95)
    base_conf = (base_spec.get("bootstrap") or {}).get("confidence", 0.95)
    if conf > base_conf:   # a wider CI reaches 0 more easily: fewer significant drops
        problems.append(f"ratchet: bootstrap confidence {base_conf} -> {conf} widens the CI")
    mine = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = mine.get(bm["id"])
        if m is None:
            problems.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"ratchet: metric {bm['id']} no longer blocking")
        if bm.get("kind") != m.get("kind"):
            problems.append(f"ratchet: metric {bm['id']} kind {bm.get('kind')} -> {m.get('kind')}")
        problems += [f"ratchet: metric {bm['id']} {x}"
                     for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    mine_sl = {(x.get("name"), x.get("metric")): x for x in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        sid = f"{bsl.get('name')}/{bsl.get('metric')}"
        x = mine_sl.get((bsl.get("name"), bsl.get("metric")))
        if x is None:
            problems.append(f"ratchet: slice {sid} removed")
            continue
        if bsl.get("blocking") and not x.get("blocking"):
            problems.append(f"ratchet: slice {sid} no longer blocking")
        problems += [f"ratchet: slice {sid} {d}" for d in _looser(x, bsl)]
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                     # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
