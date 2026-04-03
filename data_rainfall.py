"""
CHIRPS rainfall anomaly data loader for Somalia.
Downloads subnational dekadal rainfall data from HDX and returns per-region summaries.
"""

import requests
import pandas as pd
import io

RAINFALL_URL = (
    "https://data.humdata.org/dataset/ed6e1b4b-8094-47e6-bdf7-f6d56fa7abb9"
    "/resource/60b799a6-fe0a-4fa8-918f-5a5b6256eb7c"
    "/download/som-rainfall-subnat-5ytd.csv"
)

# Somalia PCODE → ACLED admin1 name
PCODE_TO_ACLED = {
    "SO11": "Awdal",
    "SO12": "Woqooyi Galbeed",
    "SO13": "Togdheer",
    "SO14": "Sool",
    "SO15": "Sanaag",
    "SO16": "Bari",
    "SO17": "Nugaal",
    "SO18": "Mudug",
    "SO19": "Galgaduud",
    "SO20": "Hiraan",
    "SO21": "Middle Shabelle",
    "SO22": "Banadir",
    "SO23": "Lower Shabelle",
    "SO24": "Bay",
    "SO25": "Bakool",
    "SO26": "Gedo",
    "SO27": "Middle Juba",
    "SO28": "Lower Juba",
}


def rainfall_status(r3q):
    """Plain-English status for a 3-month rainfall anomaly percentage."""
    if r3q is None:
        return "unknown"
    if r3q < 60:
        return "severe drought"
    if r3q < 80:
        return "drought"
    if r3q < 95:
        return "below average"
    if r3q <= 110:
        return "normal"
    if r3q <= 130:
        return "above average"
    return "heavy rainfall"


def get_rainfall_summary(url=RAINFALL_URL):
    """
    Return a dict keyed by ACLED admin1 name with rainfall anomaly data
    for the most recent available dekad.

    Each value:
        pcode    : Somalia PCODE
        date     : reporting date string (YYYY-MM-DD)
        version  : 'final' or 'forecast'
        r3q      : 3-month rainfall anomaly (% of 1989-2018 average)
        r1q      : 1-month anomaly
        rfq      : current dekad anomaly
        status   : plain-English status derived from r3q
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))

    df_adm1 = df[df["adm_level"] == 1].copy()
    if df_adm1.empty:
        raise ValueError("No admin1 rows found in rainfall CSV.")

    df_adm1["date"] = pd.to_datetime(df_adm1["date"])
    latest_date = df_adm1["date"].max()
    df_latest = df_adm1[df_adm1["date"] == latest_date]
    date_str = latest_date.strftime("%Y-%m-%d")

    results = {}
    for _, row in df_latest.iterrows():
        pcode = str(row["PCODE"]).strip()
        acled_region = PCODE_TO_ACLED.get(pcode)
        if acled_region is None:
            continue

        def _float(val):
            return round(float(val), 1) if pd.notna(val) else None

        r3q = _float(row["r3q"])
        results[acled_region] = {
            "pcode": pcode,
            "date": date_str,
            "version": str(row.get("version", "")).strip(),
            "r3q": r3q,
            "r1q": _float(row["r1q"]),
            "rfq": _float(row["rfq"]),
            "status": rainfall_status(r3q),
        }

    return results


def format_rainfall_for_prompt(rainfall_data):
    """Format rainfall data as text block for the Claude prompt."""
    if not rainfall_data:
        return ""

    sample = next(iter(rainfall_data.values()))
    date_str = sample.get("date", "unknown")
    version = sample.get("version", "")
    version_note = " (forecast — not yet finalised)" if version == "forecast" else ""

    lines = [
        f"CHIRPS RAINFALL DATA — 3-month anomaly vs 1989-2018 baseline "
        f"(dekad ending {date_str}{version_note}):",
        "Values are % of long-term average. "
        "Below 80% = drought. 80-95% = below average. 95-110% = normal. "
        "110-130% = above average. Above 130% = heavy rainfall.",
        "",
    ]

    for region, data in sorted(rainfall_data.items(), key=lambda x: x[1].get("r3q") or 100):
        r3q = data.get("r3q")
        r1q = data.get("r1q")
        status = data.get("status", "unknown")
        r3q_str = f"{r3q:.0f}%" if r3q is not None else "n/a"
        r1q_str = f"{r1q:.0f}%" if r1q is not None else "n/a"
        lines.append(f"  {region}: {r3q_str} of normal ({status}) | 1-month: {r1q_str}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Downloading CHIRPS rainfall data...")
    data = get_rainfall_summary()
    print(f"Loaded data for {len(data)} regions.\n")
    print(format_rainfall_for_prompt(data))
