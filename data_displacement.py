"""
Somalia IDP displacement data loader.

Primary source: UNHCR/OCHA Harmonised IDP Figures (HDX), district-level,
aggregated to admin1. More recent and cross-agency than DTM alone.

Supplementary: IOM DTM API V3 admin1 data, used only for regions absent
from the harmonised file.
"""

import io
import os
import requests
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# ── Primary source ───────────────────────────────────────────────────────────
# UNHCR/OCHA Harmonised IDP Figures – Sep 2025
HARMONISED_IDP_URL = (
    "https://data.humdata.org/dataset/f0771914-3a30-4c79-8525-7d351fee3751"
    "/resource/445ce158-42fb-4221-9998-d04be2ee6b37"
    "/download/idp-consolidated-file-spatial-results-sep2025-share.xlsx"
)
HARMONISED_IDP_DATE = "2025-09-30"

# ── Supplementary source ─────────────────────────────────────────────────────
DTM_API_URL = "https://dtmapi.iom.int/v3/displacement/admin1"

# Region name → ACLED admin1 name (covers both source naming variants)
REGION_TO_ACLED = {
    # Harmonised file names (already match ACLED in most cases)
    "Awdal": "Awdal",
    "Bakool": "Bakool",
    "Banadir": "Banadir",
    "Bari": "Bari",
    "Bay": "Bay",
    "Galgaduud": "Galgaduud",
    "Gedo": "Gedo",
    "Hiraan": "Hiraan",
    "Lower Juba": "Lower Juba",
    "Lower Shabelle": "Lower Shabelle",
    "Middle Juba": "Middle Juba",
    "Middle Shabelle": "Middle Shabelle",
    "Mudug": "Mudug",
    "Nugaal": "Nugaal",
    "Sanaag": "Sanaag",
    "Sool": "Sool",
    "Togdheer": "Togdheer",
    "Woqooyi Galbeed": "Woqooyi Galbeed",
    # DTM name variants
    "Woqooyi Galbeed (Hargeisa)": "Woqooyi Galbeed",
    "Hiran": "Hiraan",
    "Middle Shebelle": "Middle Shabelle",
    "Lower Shebelle": "Lower Shabelle",
    "Middle Jubba": "Middle Juba",
    "Lower Jubba": "Lower Juba",
}


# ── Harmonised IDP (primary) ──────────────────────────────────────────────────

def get_harmonised_idp_summary(url=HARMONISED_IDP_URL):
    """
    Download and aggregate the UNHCR/OCHA Harmonised IDP XLSX to admin1 level.

    Returns a dict keyed by ACLED admin1 name:
        idps           : total IDP individuals
        reporting_date : dataset reference date
        source         : "UNHCR/OCHA Harmonised"
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    df = pd.read_excel(io.BytesIO(response.content), sheet_name="Sheet1")

    # Drop the grand-total row and any rows with no region
    df = df.dropna(subset=["Region"])
    df = df[df["Region"].str.strip().str.lower() != "total"]

    # Coerce IDP figures to numeric
    df["Harmonised IDP figures"] = pd.to_numeric(
        df["Harmonised IDP figures"], errors="coerce"
    ).fillna(0)

    # Aggregate district rows to admin1
    admin1_totals = df.groupby("Region")["Harmonised IDP figures"].sum()

    results = {}
    for raw_region, total in admin1_totals.items():
        acled_name = REGION_TO_ACLED.get(raw_region.strip())
        if acled_name is None:
            continue
        results[acled_name] = {
            "idps": int(round(total)),
            "reporting_date": HARMONISED_IDP_DATE,
            "source": "UNHCR/OCHA Harmonised",
        }

    return results


# ── DTM API (supplementary) ───────────────────────────────────────────────────

def _get_dtm_summary(api_key=None):
    """Internal helper: fetch DTM admin1 data, return most-recent-date records."""
    if api_key is None:
        api_key = os.getenv("DTM_API_KEY")
    if not api_key:
        raise ValueError("DTM_API_KEY not set.")

    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "User-Agent": "somalia-conflict-monitor",
    }
    response = requests.get(
        DTM_API_URL,
        headers=headers,
        params={"CountryName": "Somalia"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    records = (
        data.get("result") or data.get("value") or
        data.get("data") or data.get("results") or []
    ) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    if not records:
        return {}

    latest_date = max(
        (str(r.get("reportingDate") or "")[:10] for r in records if r.get("reportingDate")),
        default="unknown",
    )

    results = {}
    for record in records:
        if str(record.get("reportingDate") or "")[:10] != latest_date:
            continue
        raw_name = (record.get("admin1Name") or "").strip()
        acled_name = REGION_TO_ACLED.get(raw_name)
        if acled_name is None:
            continue
        idps = int(record.get("numPresentIdpInd") or 0)
        if acled_name in results:
            results[acled_name]["idps"] += idps
        else:
            results[acled_name] = {
                "idps": idps,
                "reporting_date": latest_date,
                "source": "IOM DTM",
            }
    return results


# ── Public interface ──────────────────────────────────────────────────────────

def get_displacement_summary():
    """
    Return a dict keyed by ACLED admin1 name with IDP displacement figures.

    Uses UNHCR/OCHA Harmonised IDP figures as the primary source.
    Supplements with IOM DTM data for any regions absent from harmonised file.

    Each value:
        idps           : total IDP individuals
        reporting_date : reporting date string
        source         : data source label
    """
    results = {}
    primary_error = None
    dtm_error = None

    # Primary: harmonised file
    try:
        results = get_harmonised_idp_summary()
    except Exception as e:
        primary_error = e

    # Supplementary: DTM for any regions not covered by harmonised file
    try:
        dtm_data = _get_dtm_summary()
        for region, data in dtm_data.items():
            if region not in results:
                results[region] = data
    except Exception as e:
        dtm_error = e

    if primary_error and dtm_error:
        raise RuntimeError(
            f"Both displacement sources failed. "
            f"Harmonised: {primary_error}. DTM: {dtm_error}"
        )
    if primary_error:
        print(f"  Warning: Harmonised IDP source failed ({primary_error}); "
              f"using DTM only.")
    if dtm_error:
        print(f"  Note: DTM supplementary source unavailable ({dtm_error}).")

    return results


def format_displacement_for_prompt(displacement_data):
    """Format displacement data as text block for the Claude prompt."""
    if not displacement_data:
        return ""

    active = {r: d for r, d in displacement_data.items() if d.get("idps", 0) > 0}
    if not active:
        return ""

    # Summarise sources present
    sources = sorted(set(d["source"] for d in active.values()))
    dates = sorted(set(d["reporting_date"] for d in active.values()), reverse=True)
    source_note = "; ".join(sources)
    date_note = dates[0] if len(dates) == 1 else f"various ({', '.join(dates[:2])})"

    lines = [
        f"IDP DISPLACEMENT DATA — Internally Displaced Persons by admin1 region",
        f"Source: {source_note} | Reference date: {date_note}",
        "",
    ]
    for region, data in sorted(active.items(), key=lambda x: x[1]["idps"], reverse=True):
        src_tag = "" if data["source"] == "UNHCR/OCHA Harmonised" else f" [{data['source']}]"
        lines.append(f"  {region}: {data['idps']:,} IDPs{src_tag}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Loading displacement data...")
    data = get_displacement_summary()
    print(f"Loaded data for {len(data)} regions.\n")
    print(format_displacement_for_prompt(data))
