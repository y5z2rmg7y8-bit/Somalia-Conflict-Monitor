"""
seasonal_analysis.py
Seasonal baseline and anomaly detection for the Somalia Conflict Monitor.
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ============================================================
# HELPER: Monthly counts table
# ============================================================

def _get_monthly_counts(df):
    """
    Returns a DataFrame with columns:
        admin1, year_month (Period[M]), cal_month, year, events, fatalities
    Full cross-product of all regions x all months in dataset range, zeros filled.
    """
    df = df.copy()
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["year_month"] = df["event_date"].dt.to_period("M")

    # Aggregate observed counts
    agg = (
        df.groupby(["admin1", "year_month"])
        .agg(events=("event_id_cnty", "count"), fatalities=("fatalities", "sum"))
        .reset_index()
    )

    # Full cross-product: all regions x all months
    all_regions = df["admin1"].dropna().unique().tolist()
    all_months = pd.period_range(
        start=df["year_month"].min(),
        end=df["year_month"].max(),
        freq="M"
    )
    idx = pd.MultiIndex.from_product([all_regions, all_months], names=["admin1", "year_month"])
    full = pd.DataFrame(index=idx).reset_index()
    full["events"] = 0
    full["fatalities"] = 0

    # Merge observed onto full
    full = full.set_index(["admin1", "year_month"])
    agg_idx = agg.set_index(["admin1", "year_month"])
    full.update(agg_idx)
    full = full.reset_index()

    full["cal_month"] = full["year_month"].dt.month
    full["year"] = full["year_month"].dt.year
    full["events"] = full["events"].astype(int)
    full["fatalities"] = full["fatalities"].astype(int)

    return full


# ============================================================
# Component 1: Compute seasonal baselines
# ============================================================

def compute_seasonal_baselines(df, exclude_month_start=None):
    """
    For each region and calendar month (1-12), collect monthly event counts
    from all available observations in df, optionally excluding a given month.

    Returns {region: {cal_month: {mean, p20, p80, n_obs, values}}}
    """
    monthly = _get_monthly_counts(df)

    if exclude_month_start is not None:
        exclude_period = pd.Period(exclude_month_start, freq="M")
        monthly = monthly[monthly["year_month"] != exclude_period]

    baselines = {}
    for region, grp in monthly.groupby("admin1"):
        baselines[region] = {}
        for cal_month, sub in grp.groupby("cal_month"):
            values = sub["events"].tolist()
            arr = np.array(values, dtype=float)
            baselines[region][cal_month] = {
                "mean": float(np.mean(arr)),
                "p20": float(np.percentile(arr, 20)),
                "p80": float(np.percentile(arr, 80)),
                "n_obs": int(len(arr)),
                "values": [int(v) for v in values],
            }

    return baselines


# ============================================================
# Component 2: Detect current anomalies
# ============================================================

def detect_current_anomalies(df, current_month_start):
    """
    Build baselines (excluding current month), compare each region's count
    in the reporting month to its cal-month baseline. Flag above p80 or below p20.

    Returns sorted list of dicts.
    """
    baselines = compute_seasonal_baselines(df, exclude_month_start=current_month_start)

    current_period = pd.Period(current_month_start, freq="M")
    cal_month = current_period.month

    monthly = _get_monthly_counts(df)
    current_counts = monthly[monthly["year_month"] == current_period].set_index("admin1")["events"].to_dict()

    anomalies = []
    for region, cal_baselines in baselines.items():
        if cal_month not in cal_baselines:
            continue
        baseline = cal_baselines[cal_month]
        current_events = current_counts.get(region, 0)

        if current_events > baseline["p80"]:
            direction = "above"
        elif current_events < baseline["p20"]:
            direction = "below"
        else:
            continue

        if baseline["mean"] > 0:
            magnitude_pct = float((current_events - baseline["mean"]) / baseline["mean"] * 100)
        else:
            magnitude_pct = float("inf") if current_events > 0 else 0.0

        anomalies.append({
            "region": region,
            "cal_month": cal_month,
            "current_events": int(current_events),
            "mean": float(baseline["mean"]),
            "p20": float(baseline["p20"]),
            "p80": float(baseline["p80"]),
            "direction": direction,
            "magnitude_pct": round(magnitude_pct, 1),
            "n_obs": int(baseline["n_obs"]),
        })

    # Sort: above first (by magnitude desc), then below (by magnitude asc)
    above = sorted([a for a in anomalies if a["direction"] == "above"],
                   key=lambda x: x["magnitude_pct"], reverse=True)
    below = sorted([a for a in anomalies if a["direction"] == "below"],
                   key=lambda x: x["magnitude_pct"])
    return above + below


# ============================================================
# Component 3: Format seasonal context for prompt injection
# ============================================================

def format_seasonal_for_prompt(anomalies, current_month_start, anomaly_eval=None):
    """
    Build a text block for injection into the user message.
    """
    if not anomalies:
        return ""

    current_period = pd.Period(current_month_start, freq="M")
    cal_month = current_period.month
    month_name = current_period.strftime("%B %Y")

    # Rainy season note
    if cal_month in (4, 5, 6):
        season_note = "Note: this month falls within the Gu rainy season (April-June), historically associated with shifts in al-Shabaab activity and displacement patterns."
    elif cal_month in (10, 11, 12):
        season_note = "Note: this month falls within the Deyr rainy season (October-December), historically associated with flooding, displacement and changes in conflict tempo."
    else:
        season_note = ""

    by_region_eval = {}
    if anomaly_eval and "by_region" in anomaly_eval:
        by_region_eval = anomaly_eval.get("by_region", {})

    lines = [f"SEASONAL ANOMALY FLAGS — {month_name}"]
    if season_note:
        lines.append(season_note)
    lines.append("")
    lines.append("The following regions show event counts that are statistically anomalous relative to same-calendar-month baselines from prior years:")
    lines.append("")

    for a in anomalies:
        region = a["region"]
        direction = a["direction"]
        mag = a["magnitude_pct"]
        sign = "+" if direction == "above" else ""
        line = (
            f"  {region}: {direction.upper()} seasonal norm "
            f"(current: {a['current_events']} events; "
            f"baseline mean: {a['mean']:.1f}, p20: {a['p20']:.1f}, p80: {a['p80']:.1f}; "
            f"{sign}{mag:.0f}% vs mean; n={a['n_obs']} prior same-month obs)"
        )
        # Append hit-rate note if available
        if region in by_region_eval:
            reg_eval = by_region_eval[region]
            if direction == "above" and reg_eval.get("above", 0) >= 1:
                n_above = reg_eval.get("above", 0)
                n_sustained = reg_eval.get("above_sustained", 0)
                hit_rate = reg_eval.get("above_hit_rate", 0.0)
                line += (
                    f" [Historically, above-norm flags in this region were followed by "
                    f"sustained elevation in {n_sustained} of {n_above} cases ({hit_rate:.0f}%)]"
                )
            elif direction == "below" and reg_eval.get("below", 0) >= 1:
                n_below = reg_eval.get("below", 0)
                n_sustained = reg_eval.get("below_sustained", 0)
                hit_rate = reg_eval.get("below_hit_rate", 0.0)
                line += (
                    f" [Historically, below-norm flags in this region were followed by "
                    f"continued suppression in {n_sustained} of {n_below} cases ({hit_rate:.0f}%)]"
                )
        lines.append(line)

    return "\n".join(lines)


# ============================================================
# Component 4: Retrospective anomaly analysis
# ============================================================

def retrospective_anomaly_analysis(df, output_file="anomaly_evaluation.txt"):
    """
    Rolling baseline hit-rate evaluation.
    Returns a summary dict (all values JSON-serializable).
    """
    monthly = _get_monthly_counts(df)
    monthly = monthly.sort_values(["admin1", "year_month"])

    # All unique (region, year_month) pairs sorted
    all_periods = sorted(monthly["year_month"].unique().tolist())

    records = []

    for region, grp in monthly.groupby("admin1"):
        grp = grp.sort_values("year_month").reset_index(drop=True)
        period_list = grp["year_month"].tolist()
        events_by_period = dict(zip(grp["year_month"], grp["events"]))

        for i, period in enumerate(period_list):
            cal_month = period.month

            # Prior same-cal-month observations
            prior = [
                events_by_period[p]
                for p in period_list[:i]
                if p.month == cal_month
            ]
            if len(prior) < 2:
                continue

            arr = np.array(prior, dtype=float)
            p20 = float(np.percentile(arr, 20))
            p80 = float(np.percentile(arr, 80))
            current_events = int(events_by_period[period])

            if current_events > p80:
                flag = "above"
            elif current_events < p20:
                flag = "below"
            else:
                continue

            # Next month
            next_period = period + 1
            if next_period not in events_by_period:
                next_events = None
                sustained = None
            else:
                next_events = int(events_by_period[next_period])
                next_cal_month = next_period.month

                # Seasonal mean for next cal month, excluding next_period itself
                next_prior = [
                    events_by_period[p]
                    for p in period_list
                    if p.month == next_cal_month and p != next_period
                ]
                if len(next_prior) == 0:
                    sustained = None
                else:
                    next_mean = float(np.mean(next_prior))
                    if flag == "above":
                        sustained = bool(next_events > next_mean)
                    else:
                        sustained = bool(next_events < next_mean)

            records.append({
                "region": region,
                "year_month": str(period),
                "cal_month": int(cal_month),
                "current_events": current_events,
                "p20": round(p20, 2),
                "p80": round(p80, 2),
                "flag": flag,
                "next_events": next_events,
                "sustained": sustained,
            })

    # ---- Aggregate ----
    total_above = sum(1 for r in records if r["flag"] == "above")
    total_below = sum(1 for r in records if r["flag"] == "below")

    above_with_followup = [r for r in records if r["flag"] == "above" and r["sustained"] is not None]
    below_with_followup = [r for r in records if r["flag"] == "below" and r["sustained"] is not None]

    above_sustained_n = sum(1 for r in above_with_followup if r["sustained"])
    below_sustained_n = sum(1 for r in below_with_followup if r["sustained"])

    above_reverted_n = len(above_with_followup) - above_sustained_n
    below_reverted_n = len(below_with_followup) - below_sustained_n

    above_sustained_pct = float(above_sustained_n / len(above_with_followup) * 100) if above_with_followup else 0.0
    above_reverted_pct = float(above_reverted_n / len(above_with_followup) * 100) if above_with_followup else 0.0
    below_sustained_pct = float(below_sustained_n / len(below_with_followup) * 100) if below_with_followup else 0.0
    below_reverted_pct = float(below_reverted_n / len(below_with_followup) * 100) if below_with_followup else 0.0

    # By-region breakdown
    by_region = {}
    regions_seen = set(r["region"] for r in records)
    for region in regions_seen:
        reg_records = [r for r in records if r["region"] == region]
        r_above = [r for r in reg_records if r["flag"] == "above"]
        r_below = [r for r in reg_records if r["flag"] == "below"]
        r_above_wf = [r for r in r_above if r["sustained"] is not None]
        r_below_wf = [r for r in r_below if r["sustained"] is not None]
        above_sus = sum(1 for r in r_above_wf if r["sustained"])
        below_sus = sum(1 for r in r_below_wf if r["sustained"])
        by_region[region] = {
            "above": int(len(r_above)),
            "above_sustained": int(above_sus),
            "above_hit_rate": float(above_sus / len(r_above_wf) * 100) if r_above_wf else 0.0,
            "below": int(len(r_below)),
            "below_sustained": int(below_sus),
            "below_hit_rate": float(below_sus / len(r_below_wf) * 100) if r_below_wf else 0.0,
        }

    # Reliability ranking (regions with >= 2 above-norm flags)
    ranked_regions = [
        (region, v["above_hit_rate"])
        for region, v in by_region.items()
        if v["above"] >= 2
    ]
    ranked_regions.sort(key=lambda x: x[1], reverse=True)
    most_reliable = [r[0] for r in ranked_regions[:3]] if ranked_regions else []
    least_reliable = [r[0] for r in ranked_regions[-3:]] if ranked_regions else []

    # Plain-English assessment
    if above_sustained_pct >= 60:
        predictive_strength = "strong"
    elif above_sustained_pct >= 45:
        predictive_strength = "moderate"
    else:
        predictive_strength = "limited"

    summary = {
        "total_above": int(total_above),
        "total_below": int(total_below),
        "above_with_followup": int(len(above_with_followup)),
        "below_with_followup": int(len(below_with_followup)),
        "above_sustained_n": int(above_sustained_n),
        "above_reverted_n": int(above_reverted_n),
        "below_sustained_n": int(below_sustained_n),
        "below_reverted_n": int(below_reverted_n),
        "above_sustained_pct": round(above_sustained_pct, 1),
        "above_reverted_pct": round(above_reverted_pct, 1),
        "below_sustained_pct": round(below_sustained_pct, 1),
        "below_reverted_pct": round(below_reverted_pct, 1),
        "predictive_strength": predictive_strength,
        "most_reliable_regions": most_reliable,
        "least_reliable_regions": least_reliable,
        "by_region": by_region,
        "anomaly_records": records,
    }

    # ---- Write report ----
    report_lines = [
        "SOMALIA CONFLICT MONITOR — RETROSPECTIVE ANOMALY EVALUATION",
        "=" * 60,
        "",
        "OVERALL HIT RATES",
        "-" * 40,
        f"Total above-norm flags:  {total_above}",
        f"  With followup month:   {len(above_with_followup)}",
        f"  Sustained elevation:   {above_sustained_n} ({above_sustained_pct:.1f}%)",
        f"  Reverted next month:   {above_reverted_n} ({above_reverted_pct:.1f}%)",
        "",
        f"Total below-norm flags:  {total_below}",
        f"  With followup month:   {len(below_with_followup)}",
        f"  Continued suppression: {below_sustained_n} ({below_sustained_pct:.1f}%)",
        f"  Reverted next month:   {below_reverted_n} ({below_reverted_pct:.1f}%)",
        "",
        "PLAIN-ENGLISH ASSESSMENT",
        "-" * 40,
        f"Above-norm anomaly flags have {predictive_strength} predictive value: "
        f"{above_sustained_pct:.0f}% of above-norm flags were followed by sustained "
        f"elevated activity in the subsequent month.",
        "",
        "REGIONAL BREAKDOWN",
        "-" * 40,
        f"{'Region':<30} {'Above':>6} {'Sust':>5} {'Hit%':>6}  {'Below':>6} {'Sust':>5} {'Hit%':>6}",
        "-" * 70,
    ]

    for region in sorted(by_region.keys()):
        v = by_region[region]
        report_lines.append(
            f"{region:<30} {v['above']:>6} {v['above_sustained']:>5} {v['above_hit_rate']:>5.0f}%"
            f"  {v['below']:>6} {v['below_sustained']:>5} {v['below_hit_rate']:>5.0f}%"
        )

    report_lines += [
        "",
        "RELIABILITY BY REGION (above-norm flags, ≥2 observations)",
        "-" * 40,
    ]
    if most_reliable:
        report_lines.append(f"Most reliable:  {', '.join(most_reliable)}")
    if least_reliable:
        report_lines.append(f"Least reliable: {', '.join(least_reliable)}")

    report_lines += [
        "",
        "METHODOLOGICAL NOTE",
        "-" * 40,
        "This evaluation uses a rolling out-of-sample approach: baselines are computed",
        "from prior same-calendar-month observations only. Flags require ≥2 prior",
        "observations. 'Sustained' = the following month's count exceeds (above-norm) or",
        "falls below (below-norm) the full-dataset mean for that calendar month.",
        "Small sample sizes (often 2-3 prior observations per calendar month) mean",
        "percentile thresholds are sensitive to individual outliers. Interpret hit rates",
        "with caution, particularly for regions with few flags.",
    ]

    with open(output_file, "w") as f:
        f.write("\n".join(report_lines))

    print(f"[Seasonal] Anomaly evaluation report written: {output_file}")
    print(f"[Seasonal] Above-norm hit rate: {above_sustained_pct:.1f}% ({above_sustained_n}/{len(above_with_followup)} with followup)")
    print(f"[Seasonal] Below-norm hit rate: {below_sustained_pct:.1f}% ({below_sustained_n}/{len(below_with_followup)} with followup)")

    return summary
