"""
Somalia admin1 population data.
Uses UNFPA 2021 projections (most recent available admin-level estimates).
WorldPop for Somalia only provides raster GeoTIFFs; tabular admin-level data
comes from the UNFPA/OCHA Common Operational Dataset (cod-ps-som).
"""

import pandas as pd

# UNFPA 2021 population projections, aggregated to admin1.
# Source: population-15.7_final.xlsx from HDX dataset cod-ps-som.
# These are projections, not a new census.
POPULATION_2021 = {
    "Awdal": 538209,
    "Woqooyi Galbeed": 1224715,
    "Togdheer": 728224,
    "Sool": 464487,
    "Sanaag": 362723,
    "Bari": 1042591,
    "Nugaal": 534574,
    "Mudug": 1244026,
    "Galgaduud": 687573,
    "Hiraan": 427124,
    "Middle Shabelle": 857395,
    "Banadir": 2683312,
    "Lower Shabelle": 1347933,
    "Bay": 1055913,
    "Bakool": 459747,
    "Gedo": 736704,
    "Middle Juba": 363930,
    "Lower Juba": 979998,
}

DATA_YEAR = 2021
DATA_SOURCE = "UNFPA 2021 projection"


def get_population_summary():
    """
    Return a dict keyed by ACLED admin1 name with population figures.

    Each value:
        population : total population estimate
        year       : data year
        source     : data source description
    """
    return {
        region: {
            "population": pop,
            "year": DATA_YEAR,
            "source": DATA_SOURCE,
        }
        for region, pop in POPULATION_2021.items()
    }


def compute_per_capita(population_data, reporting_df):
    """
    Compute per-capita conflict event and fatality rates for the reporting month.

    Returns a dict keyed by ACLED admin1 name:
        population          : total population
        events              : raw event count
        fatalities          : raw fatality count
        events_per_100k     : events per 100,000 population
        fatalities_per_100k : fatalities per 100,000 population
    """
    if not population_data or reporting_df is None or reporting_df.empty:
        return {}

    event_counts = reporting_df["admin1"].value_counts()
    fatality_counts = reporting_df.groupby("admin1")["fatalities"].sum()

    results = {}
    for region, data in population_data.items():
        pop = data["population"]
        events = int(event_counts.get(region, 0))
        fatalities = int(fatality_counts.get(region, 0))
        if pop > 0:
            events_per_100k = round(events / pop * 100000, 1)
            fat_per_100k = round(fatalities / pop * 100000, 1)
        else:
            events_per_100k = 0.0
            fat_per_100k = 0.0
        results[region] = {
            "population": pop,
            "events": events,
            "fatalities": fatalities,
            "events_per_100k": events_per_100k,
            "fatalities_per_100k": fat_per_100k,
        }

    return results


def format_population_for_prompt(per_capita_data):
    """Format per-capita rates as text for the Claude prompt."""
    if not per_capita_data:
        return ""

    # Only include regions with at least 1 event
    active = {r: d for r, d in per_capita_data.items() if d["events"] > 0}
    if not active:
        return ""

    lines = [
        f"POPULATION AND PER-CAPITA CONFLICT RATES (reporting month) — "
        f"Source: UNFPA {DATA_YEAR} population projections:",
        "",
    ]

    for region, data in sorted(active.items(), key=lambda x: x[1]["events_per_100k"], reverse=True):
        lines.append(
            f"  {region}: pop {data['population']:,} | "
            f"{data['events']} events ({data['events_per_100k']} per 100k) | "
            f"{data['fatalities']} fatalities ({data['fatalities_per_100k']} per 100k)"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    import pandas as pd
    data = get_population_summary()
    print(f"Population data for {len(data)} regions ({DATA_SOURCE}):\n")
    for region, info in sorted(data.items(), key=lambda x: -x[1]["population"]):
        print(f"  {region}: {info['population']:,}")
