"""
IPC food security data loader for Somalia.
Downloads the latest IPC Phase data from HDX and returns per-region summaries.
"""

import requests
import pandas as pd
import io

IPC_URL = (
    "https://data.humdata.org/dataset/26cac16a-98cd-4c4e-9353-40bd423302c0"
    "/resource/487e478e-7fc3-4020-91eb-44af61a264ce"
    "/download/ipc_som_level1_long_latest.csv"
)

# Map IPC Level 1 names → ACLED admin1 names
# IPC uses older Somali region names; ACLED uses a mix of English and Somali
IPC_TO_ACLED = {
    "Awdal": "Awdal",
    "Bakool": "Bakool",
    "Banadir": "Banadir",
    "Bari": "Bari",
    "Bay": "Bay",
    "Galgaduud": "Galgaduud",
    "Gedo": "Gedo",
    "Hiraan": "Hiraan",
    "Juba Dhexe": "Middle Juba",
    "Juba dhexe": "Middle Juba",
    "Juba Hoose": "Lower Juba",
    "Juba hoose": "Lower Juba",
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
}

PHASE_LABELS = {
    1: "Phase 1 (Minimal)",
    2: "Phase 2 (Stressed)",
    3: "Phase 3 (Crisis)",
    "3+": "Phase 3+ (Crisis or worse)",
    4: "Phase 4 (Emergency)",
    5: "Phase 5 (Famine)",
    "all": "All phases",
}


def load_ipc_data(url=IPC_URL):
    """Download and return the raw IPC CSV as a DataFrame."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    return df


def get_ipc_summary(url=IPC_URL):
    """
    Return a dict keyed by ACLED admin1 region name with IPC phase summary
    for the most recent current-period analysis.

    Each value is a dict with:
        ipc_region       : original IPC region name
        analysis_date    : date of analysis (string)
        validity_from    : start of validity period (string)
        validity_to      : end of validity period (string)
        dominant_phase   : highest phase with population data (int or str)
        population_in_crisis : population in Phase 3+ (int or None)
        population_in_emergency : population in Phase 4+ (int or None)
        population_in_famine : population in Phase 5 (int or None)
        phase_populations : dict of {phase: population} for all phases
    """
    df = load_ipc_data(url)

    # Normalise column names
    df.columns = [c.strip() for c in df.columns]

    # Filter to current validity period only
    df_current = df[df["Validity period"].str.strip().str.lower() == "current"].copy()

    if df_current.empty:
        raise ValueError("No rows with Validity period = 'current' found in IPC data.")

    # Find the most recent analysis date
    df_current["Date of analysis"] = pd.to_datetime(
        df_current["Date of analysis"], dayfirst=True, errors="coerce"
    )
    latest_date = df_current["Date of analysis"].max()
    df_latest = df_current[df_current["Date of analysis"] == latest_date].copy()

    analysis_date_str = latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "unknown"

    results = {}

    for ipc_region, group in df_latest.groupby("Level 1"):
        ipc_region = ipc_region.strip()
        acled_region = IPC_TO_ACLED.get(ipc_region)
        if acled_region is None:
            # Try case-insensitive match
            for k, v in IPC_TO_ACLED.items():
                if k.lower() == ipc_region.lower():
                    acled_region = v
                    break
        if acled_region is None:
            acled_region = ipc_region  # fall back to original name

        # Build phase → population dict
        phase_populations = {}
        for _, row in group.iterrows():
            phase_raw = str(row["Phase"]).strip()
            try:
                phase_key = int(phase_raw)
            except ValueError:
                phase_key = phase_raw  # "3+", "all", etc.

            number = row["Number"]
            try:
                number = int(float(str(number).replace(",", "")))
            except (ValueError, TypeError):
                number = None

            phase_populations[phase_key] = number

        # Validity period
        validity_from = group["From"].iloc[0] if "From" in group.columns else None
        validity_to = group["To"].iloc[0] if "To" in group.columns else None

        # Population in crisis (Phase 3+): sum of phases 3, 3+, 4, 5
        # IPC defines "3+" as 3 or above — use it directly if present, else sum 3+4+5
        pop_3plus = phase_populations.get("3+")
        pop_3 = phase_populations.get(3)
        pop_4 = phase_populations.get(4)
        pop_5 = phase_populations.get(5)

        if pop_3plus is not None:
            population_in_crisis = pop_3plus
        else:
            # Sum phases 3, 4, 5
            parts = [p for p in [pop_3, pop_4, pop_5] if p is not None]
            population_in_crisis = sum(parts) if parts else None

        population_in_emergency = None
        if pop_4 is not None or pop_5 is not None:
            parts = [p for p in [pop_4, pop_5] if p is not None]
            population_in_emergency = sum(parts) if parts else None

        population_in_famine = pop_5

        # Dominant phase: highest phase with non-zero population
        ordered_phases = [5, 4, "3+", 3, 2, 1]
        dominant_phase = None
        for ph in ordered_phases:
            pop = phase_populations.get(ph)
            if pop and pop > 0:
                dominant_phase = ph
                break

        results[acled_region] = {
            "ipc_region": ipc_region,
            "analysis_date": analysis_date_str,
            "validity_from": str(validity_from) if validity_from else None,
            "validity_to": str(validity_to) if validity_to else None,
            "dominant_phase": dominant_phase,
            "population_in_crisis": population_in_crisis,
            "population_in_emergency": population_in_emergency,
            "population_in_famine": population_in_famine,
            "phase_populations": phase_populations,
        }

    return results


def format_ipc_for_prompt(ipc_data):
    """
    Format IPC data as a text block for inclusion in the Claude prompt.
    Returns a string summarising current IPC phase classifications by region.
    """
    if not ipc_data:
        return ""

    # Get analysis date from first entry
    sample = next(iter(ipc_data.values()))
    analysis_date = sample.get("analysis_date", "unknown")
    validity_from = sample.get("validity_from", "")
    validity_to = sample.get("validity_to", "")

    lines = [
        f"IPC FOOD SECURITY DATA (analysis date: {analysis_date}; "
        f"validity: {validity_from} to {validity_to})",
        "",
        "IPC Phase classifications by region (current period):",
        "Phase 1=Minimal, 2=Stressed, 3=Crisis, 4=Emergency, 5=Famine",
        "",
    ]

    # Sort by population in crisis descending
    sorted_regions = sorted(
        ipc_data.items(),
        key=lambda x: x[1].get("population_in_crisis") or 0,
        reverse=True,
    )

    for acled_region, data in sorted_regions:
        pop_crisis = data.get("population_in_crisis")
        pop_emergency = data.get("population_in_emergency")
        pop_famine = data.get("population_in_famine")
        dominant = data.get("dominant_phase")

        crisis_str = f"{pop_crisis:,}" if pop_crisis is not None else "n/a"
        emergency_str = f"{pop_emergency:,}" if pop_emergency is not None else "n/a"
        famine_str = f"{pop_famine:,}" if pop_famine is not None else "n/a"
        dominant_str = str(dominant) if dominant is not None else "n/a"

        lines.append(
            f"  {acled_region}: dominant phase {dominant_str} | "
            f"Phase 3+ (crisis): {crisis_str} | "
            f"Phase 4+ (emergency): {emergency_str} | "
            f"Phase 5 (famine): {famine_str}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print("Downloading IPC data...")
    ipc = get_ipc_summary()
    print(f"Loaded data for {len(ipc)} regions.\n")
    print(format_ipc_for_prompt(ipc))
