import requests
import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv
from format_docx import create_brief_docx
from format_html import create_brief_html
from data_ipc import get_ipc_summary, format_ipc_for_prompt
from data_rainfall import get_rainfall_summary, format_rainfall_for_prompt
from data_population import get_population_summary, compute_per_capita, format_population_for_prompt
from data_displacement import get_displacement_summary, format_displacement_for_prompt
from post_processing import filter_superlatives
import os
import json
from datetime import datetime

# Load credentials
load_dotenv()

# Load analyst knowledge file (if present)
_knowledge_file = "analyst_knowledge.txt"
if os.path.exists(_knowledge_file):
    with open(_knowledge_file, "r") as _f:
        ANALYST_KNOWLEDGE = _f.read().strip()
    print(f"Analyst knowledge file loaded: {_knowledge_file}")
else:
    ANALYST_KNOWLEDGE = None
    print(f"Warning: {_knowledge_file} not found — running without standing context.")
email = os.getenv("ACLED_EMAIL")
password = os.getenv("ACLED_PASSWORD")
anthropic_key = os.getenv("ANTHROPIC_API_KEY")

# ============================================================
# CONFIGURATION - change these for different reporting periods
# ============================================================
REPORTING_PERIOD = "March 2026"
DATE_START = "2023-04-01"
DATE_END = "2026-03-31"
CURRENT_MONTH_START = "2026-03-01"

# ============================================================
# CONTEXT NOTES
# Update this section before each run with terminology,
# actor definitions and any factual context the event data
# cannot capture. Do NOT include analytical judgments or
# an analytical line. The AI derives its own conclusions
# from the data.
# ============================================================
POLITICAL_CONTEXT = """
CONTEXT NOTES (factual definitions and terminology):

1. South-West State terminology: In the current South-West State (SWS) crisis, "opposition" refers to Federal-backed forces opposing the SWS administration, NOT opposition to the Federal Government. The SWS Special Police Forces (SWSPF) are split between units loyal to the SWS administration and units that defected to Federal alignment. Use precise language to distinguish these factions. By the end of March 2026, the SWS administration had capitulated and the SWS President had resigned. Federal control was restored. Federal re-establishment of control was less violent than expected but not peaceful. Do not characterise it as either a bloodless takeover or a major military operation without evidence from the data. Federal-SWS combat was isolated rather than sustained. The collapse of SWS resistance did not generate prolonged fighting. Do not characterise Federal operations against SWS as "sustained combat operations" or "sustained military campaign".

2. Federal forces: Federal forces deployed to South-West State. Do not refer to "Harmacad" forces by name. Use "Federal security forces" or "Federal forces" as the default term for all Federal deployments to South-West State. Do not attribute actions to a specific unit unless the data names it explicitly and unambiguously.

3. AUSSOM: The African Union Support and Stabilisation Mission in Somalia (AUSSOM) replaced ATMIS in early 2025. Use "AUSSOM" throughout.

4. Key actor translations: "Military Forces of Somalia (2022-)" = Somali National Army (SNA) forces. "Al Shabaab" = al-Shabaab. "South West State Special Police Forces" = SWSPF. Spell out "Islamic State Somalia Province (ISSP)" on first use, then use "ISSP" thereafter.

5. Baidoa geography: Baidoa is an inland city, not a port. Do not reference port facilities or maritime escape routes in connection with Baidoa or Bay region.
"""

# ============================================================
# PREVIOUS MONTH'S PREDICTIONS (for forecast review)
# Auto-loaded from file if available.
# ============================================================
predictions_file = "previous_predictions.txt"
if os.path.exists(predictions_file):
    with open(predictions_file, "r") as f:
        PREVIOUS_PREDICTIONS = f.read()
else:
    PREVIOUS_PREDICTIONS = "No previous predictions available. This is the first brief in the series."

# ============================================================
# STEP 1: AUTHENTICATE WITH ACLED
# ============================================================
print("=" * 60)
print("SOMALIA CONFLICT MONITOR PIPELINE")
print("=" * 60)
print("\n[1/6] Authenticating with ACLED...")

auth_response = requests.post(
    "https://acleddata.com/oauth/token",
    data={
        "username": email,
        "email": email,
        "password": password,
        "grant_type": "password",
        "client_id": "acled"
    }
)

if auth_response.status_code != 200:
    print(f"Authentication failed: {auth_response.status_code}")
    print(auth_response.text)
    exit()

access_token = auth_response.json()["access_token"]
print("Authentication successful.")

# ============================================================
# STEP 2: PULL ACLED DATA (paginated)
# ============================================================
print("\n[2/6] Fetching Somalia conflict data...")

all_data = []
page = 1
while True:
    response = requests.get(
        "https://acleddata.com/api/acled/read",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "country": "Somalia",
            "event_date": f"{DATE_START}|{DATE_END}",
            "event_date_where": "BETWEEN",
            "limit": 5000,
            "page": page
        }
    )
    if response.status_code != 200:
        print(f"Data request failed (page {page}): {response.status_code}")
        print(response.text)
        exit()
    page_data = response.json()["data"]
    if not page_data:
        break
    all_data.extend(page_data)
    print(f"  Page {page}: {len(page_data)} events retrieved")
    if len(page_data) < 5000:
        break
    page += 1

df = pd.DataFrame(all_data)
df["fatalities"] = df["fatalities"].astype(int)

# Reporting month
df_march = df[df["event_date"] >= CURRENT_MONTH_START].copy()

# Dynamic baseline months: all calendar months from DATE_START up to (not including) CURRENT_MONTH_START
month_starts = pd.date_range(start=DATE_START, end=CURRENT_MONTH_START, freq="MS")
baseline_month_starts = [m for m in month_starts if m < pd.Timestamp(CURRENT_MONTH_START)]

monthly_baselines = []
for i, m_start in enumerate(baseline_month_starts):
    m_end = baseline_month_starts[i + 1] if i + 1 < len(baseline_month_starts) else pd.Timestamp(CURRENT_MONTH_START)
    label = m_start.strftime("%B %Y")
    mask = (df["event_date"] >= m_start.strftime("%Y-%m-%d")) & \
           (df["event_date"] < m_end.strftime("%Y-%m-%d"))
    monthly_baselines.append({"label": label, "df": df[mask].copy()})

print(f"Total events: {len(df)}")
for m in monthly_baselines:
    print(f"  {m['label']}: {len(m['df'])}")
print(f"  {REPORTING_PERIOD} (reporting): {len(df_march)}")

# ============================================================
# STEP 2b: LOAD IPC FOOD SECURITY DATA
# ============================================================
print("\n[IPC] Loading food security data...")
try:
    ipc_data = get_ipc_summary()
    ipc_text = format_ipc_for_prompt(ipc_data)
    print(f"IPC data loaded for {len(ipc_data)} regions.")
except Exception as e:
    print(f"Warning: IPC data unavailable: {e}")
    ipc_data = {}
    ipc_text = ""

print("\n[Rainfall] Loading CHIRPS rainfall data...")
try:
    rainfall_data = get_rainfall_summary()
    rainfall_text = format_rainfall_for_prompt(rainfall_data)
    print(f"Rainfall data loaded for {len(rainfall_data)} regions.")
except Exception as e:
    print(f"Warning: Rainfall data unavailable: {e}")
    rainfall_data = {}
    rainfall_text = ""

print("\n[Population] Loading UNFPA population data...")
try:
    population_data = get_population_summary()
    print(f"Population data loaded for {len(population_data)} regions.")
except Exception as e:
    print(f"Warning: Population data unavailable: {e}")
    population_data = {}

print("\n[Displacement] Loading IOM DTM displacement data...")
try:
    displacement_data = get_displacement_summary()
    displacement_text = format_displacement_for_prompt(displacement_data)
    print(f"Displacement data loaded for {len(displacement_data)} regions.")
except Exception as e:
    print(f"Warning: Displacement data unavailable: {e}")
    displacement_data = {}
    displacement_text = ""

# ============================================================
# STEP 3: PREPARE DATA FOR CLAUDE
# ============================================================
print("\n[3/6] Preparing data and generating brief...")

summary_cols = [
    "event_id_cnty", "event_date", "event_type", "sub_event_type",
    "actor1", "actor2", "admin1", "admin2",
    "location", "fatalities", "notes"
]
march_csv = df_march[summary_cols].to_csv(index=False)


def monthly_summary(dataframe, label):
    summary = []
    summary.append(f"--- {label} ---")
    summary.append(f"Total events: {len(dataframe)}")
    summary.append(f"Total fatalities: {dataframe['fatalities'].sum()}")
    summary.append(f"\nEvents by type:")
    for etype, count in dataframe["event_type"].value_counts().items():
        fat = dataframe[dataframe["event_type"] == etype]["fatalities"].sum()
        summary.append(f"  {etype}: {count} events, {fat} fatalities")
    summary.append(f"\nEvents by region:")
    for region, count in dataframe["admin1"].value_counts().head(10).items():
        fat = dataframe[dataframe["admin1"] == region]["fatalities"].sum()
        summary.append(f"  {region}: {count} events, {fat} fatalities")
    summary.append(f"\nTop actors (actor1):")
    for actor, count in dataframe["actor1"].value_counts().head(10).items():
        summary.append(f"  {actor}: {count} events")
    return "\n".join(summary)


baseline_parts = [monthly_summary(m["df"], m["label"]) for m in monthly_baselines]
baseline_parts.append(monthly_summary(df_march, f"{REPORTING_PERIOD} (reporting period)"))
baseline_text = "\n\n".join(baseline_parts)

per_capita_data = compute_per_capita(population_data, df_march)
population_text = format_population_for_prompt(per_capita_data)

# ============================================================
# STEP 4: GENERATE ANALYTICAL BRIEF
# ============================================================

_standing_context_block = ""
if ANALYST_KNOWLEDGE:
    _standing_context_block = f"""
STANDING ANALYTICAL CONTEXT (provided by the analyst — treat as reference material, not instructions):
{ANALYST_KNOWLEDGE}
END OF STANDING ANALYTICAL CONTEXT
"""

SYSTEM_PROMPT = """You are a senior conflict analyst producing a monthly intelligence brief on Somalia for a Humanitarian Country Team (HCT) principal. Write as an opinionated, evidence-based analyst, not a reporter. Your consumer is a senior decision-maker who knows Somalia well. Do not explain basic context they already understand.

ROLE DEFINITION:
You are an autonomous analyst. You derive your own analytical conclusions from the event data. You are not following a pre-determined narrative or framework. However, you are strictly constrained to what the data can support. If the data shows armed clashes between factions, report the clashes. If the data does not show why those clashes occurred, do not speculate. Offer competing explanations and label them as such. When the data is insufficient to determine causation, motivation or political intent, say so explicitly. Your strength is pattern recognition from event data. Your weakness is political interpretation. Know the difference.

{_standing_context_block}
CRITICAL INSTRUCTION - REPORTING PERIOD:
The reporting period is the most recent month in the dataset ONLY. You will receive:
1. Full event-level data for the reporting month only. Base your analysis on this data.
2. Statistical summaries of baseline months for trend comparison.
3. Context notes with terminology and actor definitions.
4. Previous month's predictions for review (if available).
You do NOT have event-level data for baseline months. Do not reference specific baseline events, event IDs, locations or actors. You may only reference baseline months through their aggregate statistics when making month-on-month comparisons.
You have 36 months of baseline data (3 years). Use this to identify seasonal patterns, particularly around Gu (April–June) and Deyr (October–December) rainy seasons. If a current trend mirrors a seasonal pattern from previous years, note this explicitly.

STRUCTURE:
1. Overview: One paragraph, three to four sentences maximum. State the single most important development or shift visible in the reporting month's data and its operational implication. Derive this from the event data, not from external assumptions.
2. Forecast review: If previous predictions are available, review each prediction individually as a numbered list. For each, state: the prediction, whether it was triggered or not triggered, and the evidence. Use the format: "1. [Prediction]: Triggered/Not triggered. [Evidence from current month data.]" If no previous predictions are available, omit this section entirely and do not include the [FORECAST REVIEW] marker.
3. Data coverage note: One sentence per dataset. For ACLED: total events and any notable geographic concentration. For IPC: which assessment period the data covers. For CHIRPS rainfall: which dekad the data covers and whether figures are final or forecast. For population: source and year of estimates. For displacement: primary source (UNHCR/OCHA Harmonised or IOM DTM), reference date and number of regions covered. Keep each sentence brief.
4. Thematic analysis: Organise by theme, not geography. Select themes based on what the reporting month's data shows. Every paragraph must begin with a sub-heading in bold followed by a full stop in regular weight, then the paragraph text. No exceptions. Sub-headings should be in sentence case, not capitals. ACLED's "Strategic developments" category captures non-violent events with political significance, such as troop movements, territorial transfers, ceasefires and peace agreements. Define this on first use if referencing it. Do not force categories where the data is thin.
5. Geographic focus: Highlight two or three regions that warrant specific attention in the reporting month. This section must add new insight not already covered in the thematic analysis. Focus on operational or access implications specific to the location. Every paragraph must begin with a bold sub-heading followed by a regular full stop.
6. Trends and outlook: Identify trends by comparing reporting month statistics against baseline months. Draw analytical conclusions about observable patterns: changes in tempo, geographic shifts, actor behaviour and operational patterns. Do not make political predictions. Do not predict political outcomes, negotiation results, leadership decisions or institutional changes. Confine forward-looking statements to tactical and operational patterns that are directly extrapolable from event data trends. Every paragraph in this section must begin with a bold sub-heading followed by a regular full stop, consistent with all other sections.
7. What to watch: Three to five specific, observable indicators the consumer should monitor in the coming period. Each indicator must name a specific actor, location or threshold. Each indicator must include a specific threshold AND explain why that threshold was chosen, referencing the data. For example: "Al-Shabaab attacks in Lower Shabelle exceeding 15 incidents per week, up from the current average of 10, which would indicate escalation beyond the March baseline." Do not use arbitrary round numbers without justification. Present each indicator as a separate numbered item on its own line.

REFERENCE SYSTEM:
Do not cite source references inline with the text. Use sequential superscript footnote numbers (1, 2, 3 etc.) after key claims. At the end of the brief, include a section marked [REFERENCES] listing each footnote number with its source.

Reference formats by dataset:
- ACLED events: cite the specific event ID, e.g. '1. SOM56112'
- IPC data: cite as '2. IPC Phase Classification, [assessment date], [region]'
- CHIRPS rainfall: cite as '3. CHIRPS 3-month rainfall anomaly, dekad ending [date], [region]'
- WorldPop population: cite as '4. UNFPA/WorldPop population estimate, [year], [region]'
- IOM DTM displacement: cite as '5. IOM DTM Harmonised IDP Figures, [reporting date], [region]'

Every significant claim from any dataset must have a footnote. You may only cite ACLED event IDs from the reporting month's data. For other datasets, cite the source, date and region. Do not create footnotes for claims derived from the analyst-provided context notes.

IPC FOOD SECURITY DATA:
You will receive current IPC Phase classifications for Somali administrative regions. IPC phases: 1=Minimal, 2=Stressed, 3=Crisis, 4=Emergency, 5=Famine. You may reference IPC data within the thematic analysis or geographic focus where there is a direct connection to conflict patterns visible in the ACLED data. Do not write a standalone food security section. Treat IPC data as supplementary context only. If you cite an IPC figure, attribute it clearly: "According to IPC data..." and add a footnote using the IPC reference format above.

CHIRPS RAINFALL DATA:
You will receive CHIRPS dekadal rainfall anomaly data by admin1 region, showing the 3-month anomaly (r3q) as a percentage of the 1989-2018 long-term average. Values below 80% indicate drought conditions; above 120% indicates above-average rainfall. Where rainfall is significantly below or above normal, note this in the geographic focus section alongside conflict and food security data where directly relevant. Drought conditions (below 80%) are particularly relevant to displacement patterns and pastoral conflict. If the data is labelled forecast rather than final, note this. Attribute figures clearly: "According to CHIRPS data..." and add a footnote using the CHIRPS reference format above.

POPULATION AND PER-CAPITA RATES:
You will receive UNFPA 2021 population projections and per-capita conflict event rates by admin1 region for the reporting month. Use per-capita rates rather than raw event counts when comparing regions, as raw counts are misleading for regions with very different population sizes. A region with fewer total events but a higher per-capita rate may be more severely affected relative to its population. Cite per-capita rates in events per 100,000 population. Attribute figures clearly: "At X events per 100,000 population..." and add a footnote using the WorldPop reference format above.

IDP DISPLACEMENT DATA:
You will receive harmonised IDP (internally displaced person) figures by admin1 region. The primary source is the UNHCR/OCHA Harmonised IDP dataset (cross-agency, district-aggregated). Regions absent from that source are supplemented with IOM DTM API data. Where displacement figures are available, include them alongside conflict statistics in the geographic focus section where directly relevant. High displacement figures in a region experiencing active conflict may indicate population flight or prior displacement accumulation. Attribute figures clearly: "According to harmonised IDP data..." or "According to IOM DTM data..." as labelled, and add a footnote using the IOM DTM reference format above.

CROSS-DATASET ANALYSIS:
Where multiple datasets are available for a region, integrate them into a single analytical picture rather than listing each separately. Connect conflict intensity (ACLED), food security (IPC), rainfall (CHIRPS), displacement (IOM DTM) and population vulnerability into coherent assessments of humanitarian impact. A region experiencing escalating conflict, drought, high food insecurity and significant displacement simultaneously faces compounding pressures. Flag these convergences explicitly. Use per-capita rates to identify regions where raw event counts understate severity. Do not write a standalone cross-dataset section. Integrate multi-dataset analysis within the thematic analysis and geographic focus sections where supported by the data.

ANALYTICAL COMMENTARY:
Present factual statements from the data, then add analytical commentary in square brackets and italics, preceded by "Comment". For example:
"SNA forces recaptured Daarasalaam village on 2 March.1 [Comment: The speed of recapture suggests pre-positioned forces rather than a reactive deployment, though this cannot be confirmed from event data alone.]"
Apply this format to every significant analytical inference. The consumer should be able to distinguish data-derived facts from analyst interpretation at a glance.

When stating assumptions, use: [Assumption: ...]. When a significant development could plausibly be explained by more than one cause, present competing assumptions with a primary and at least one alternative. For example:
"[Assumption: Federal forces are deliberately undermining South-West State authority through targeted recruitment of SWSPF defectors. Alternative: Individual SWSPF units are defecting opportunistically in response to unpaid salaries rather than under Federal direction.]"

PROBABILITY LANGUAGE:
When making predictive judgments about tactical or operational patterns in the coming period, use these terms WITHOUT percentage ranges in the text:
   - Highly likely
   - Likely
   - Roughly even
   - Unlikely
   - Highly unlikely
Never use "almost certain" or "remote". Always state the observable basis for the judgment.

CRITICAL: Use British English probability phrasing:
Correct: "is likely to continue", "is likely to expand", "will be likely to escalate", "are likely to increase"
Incorrect: "will likely continue", "will likely expand"
Also incorrect: "will likely maintain", "will likely escalate", "will likely target".
Rewrite as: "is likely to maintain", "is likely to escalate", "is likely to target".
The pattern "will likely [verb]" is always wrong. The pattern "is/are likely to [verb]" is always correct.
The word "likely" follows "to be" or precedes "to" plus infinitive. Never place "likely" directly before a main verb without "to be".

Calibrate conservatively. Default one tier lower than your instinct. You are working from ACLED event data alone, with no human source reporting, political intelligence or direct observation.

STYLE:
- British English throughout. Active voice. Short sentences and paragraphs.
- Lead with the answer, then provide the evidence.
- No em dashes. Use full stops or commas instead.
- No Oxford comma.
- 600-800 words total. Every sentence must earn its place.
- Capitalise "Federal" when referring to the Federal Government of Somalia or Federal forces.
- Use "South-West State" (hyphenated), not "Southwest" or "Southwest State".
- SWSPF refers to South-West State Special Police Forces, not Southwest Special Police Forces.
- Spell out all acronyms and abbreviations on first use, followed by the abbreviation in brackets. Use the abbreviation thereafter.
- Where the specific Federal unit is not clearly identified in the ACLED data, use "Federal forces" as the default term.
- Translate all other ACLED actor codes into natural analytical language.
- CRITICAL FORMATTING RULE: Every paragraph in thematic analysis, geographic focus, trends and outlook, and forecast review sections must begin with a bold sub-heading followed by a full stop in regular weight, inline with the paragraph text. The sub-heading and paragraph text are part of the same paragraph, not separate elements. Format: **Sub-heading.** Paragraph text continues here. No exceptions.
- When referring to forces or factions, always specify their alignment explicitly, e.g. "South-West State administration loyalists" or "Federal-aligned SWSPF units". Do not use "administration loyalists" or "opposition forces" without specifying which side they belong to.
- Do not describe political competition between Federal and regional authorities as "territorial fragmentation". Political disputes over authority, alignment and governance are political dynamics, not territorial fragmentation. Reserve "territorial" language for physical control of land by armed groups.

BANNED PHRASES AND SUPERLATIVE RULE:
Banned words: "unprecedented", "historic", "never before", "the first time", "heaviest", "deadliest", "single largest", "single worst", "single biggest", "single most".
Banned patterns: Do not use ANY superlative or comparative construction that implies ranking across the dataset, regardless of phrasing. This includes but is not limited to: "the highest", "the lowest", "the most", "the least", "the deadliest", "the heaviest", "the worst", "the largest", "the most significant", "the most serious", "the most critical", "the most notable", "the most concerning", "the month's deadliest", "the conflict's most active", "the month's most", "the period's most", "most significant territorial consolidation". Adding qualifiers like "in the dataset", "in the reporting period", "for any region", "of any actor" does not make a superlative acceptable. It is still a superlative. Do not use "deadliest" or "most active" in any construction, even when scoped to a single month. Do not use "single largest", "single biggest", "single most", "the month's single" or any "[single] + [superlative]" construction. Do not use "the primary theatre", "the primary battleground", "the primary theatre of operations", or "primary" as a ranking term in any construction. Write "Lower Shabelle recorded 97 events, more than any other region" rather than "Lower Shabelle was the primary theatre". The ONLY permitted comparison is between two named months using specific numbers, e.g. "Lower Shabelle recorded 97 events in March, up from 72 in February".

SOMALIA-SPECIFIC CHECKS:
- Do not conflate al-Shabaab operational behaviour (attacks, ambushes, IEDs) with governance behaviour (taxation, court rulings, service provision) or political mobilisation (organised protests, rallies). Three distinct categories.
- Do not project rational-actor or Western institutional logic onto clan-based decision-making.
- Do not assume Mogadishu-based reporting is representative of conditions in southern and central regions.
- Apply scepticism to official transition timelines.
- Only reference seasonal or climate factors if mentioned in the ACLED notes field.
- Do not over-interpret single events. Look for patterns.

SELF-CHECK:
Before submitting, verify every sentence against these rules:
1. SUPERLATIVE AUDIT: For each sentence, ask: does this sentence rank, compare or elevate one thing above all others? If yes, does it name exactly two months and give specific numbers for both? If it does not meet both conditions, rewrite the sentence to state the specific number without ranking it.
2. No specific event references from baseline months.
3. No inference presented as fact without a [Comment: ...] block.
4. Every [Assumption: ...] has a competing assumption.
5. Search for every instance of the word "likely" in your response. For each instance, check: is it preceded by "is", "are", "be" or "been"? If not, rewrite the sentence. The pattern "will likely" followed by a verb is always wrong.
6. "Federal" capitalised. "South-West State" hyphenated. Not "Southwest".
7. All acronyms spelled out on first use.
8. All ACLED event IDs in footnotes, not inline. Every footnote is a SOM ID.
9. No percentage ranges with probability terms in text.
10. No political predictions. Outlook covers only tactical and operational patterns.
11. Does any claim go beyond what the event data can support? If yes, add a [Comment: ...] block acknowledging the limitation.
12. Does every paragraph in thematic analysis, geographic focus and trends sections start with a bold sub-heading followed by a regular full stop? If not, add one.
13. Check for grammar errors including subject-verb agreement.
14. Search for the word "single" in your response. For each instance followed by a superlative (largest, biggest, most, deadliest, worst, heaviest etc), remove or rewrite the sentence without the ranking construction.

FORMAT:
[OVERVIEW]
[FORECAST REVIEW]
[DATA COVERAGE]
[THEMATIC ANALYSIS]
[GEOGRAPHIC FOCUS]
[TRENDS AND OUTLOOK]
[WHAT TO WATCH]
[REFERENCES]

Omit [FORECAST REVIEW] if no previous predictions are available."""

user_message = f"""Produce the monthly intelligence brief for Somalia. The REPORTING PERIOD is {REPORTING_PERIOD}.

CONTEXT NOTES:
{POLITICAL_CONTEXT}

PREVIOUS PREDICTIONS:
{PREVIOUS_PREDICTIONS}

{REPORTING_PERIOD.upper()} EVENT DATA (full event-level detail):
{march_csv}

BASELINE STATISTICAL SUMMARIES (for trend comparison only):
{baseline_text}

{ipc_text}

{rainfall_text}

{population_text}

{displacement_text}"""

client = Anthropic(api_key=anthropic_key)
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4000,
    system=SYSTEM_PROMPT,
    messages=[
        {"role": "user", "content": user_message}
    ]
)

brief_text = response.content[0].text
brief_text = filter_superlatives(brief_text, dataset_start=DATE_START)
print("Brief generated.")

# Print brief to terminal
print("\n" + "=" * 60)
print(f"SOMALIA MONTHLY CONFLICT BRIEF")
print(f"Reporting period: {REPORTING_PERIOD}")
print("=" * 60)
print(brief_text)

# Save raw brief text
with open("brief_raw.txt", "w") as f:
    f.write(brief_text)
print("\nRaw brief saved: brief_raw.txt")

# ============================================================
# STEP 5: CREATE OUTPUTS
# ============================================================
print("\n[4/6] Creating Word document...")

docx_filename = f"somalia_brief_{REPORTING_PERIOD.lower().replace(' ', '_')}.docx"
create_brief_docx(brief_text, df, REPORTING_PERIOD, docx_filename)

# Data quality summary (computed before HTML and metadata)
data_quality = {
    "ACLED": {
        "description": "Event-level conflict and political violence data",
        "vintage": DATE_END,
        "update_frequency": "Weekly",
        "coverage": f"{len(df):,} events, {df['admin1'].nunique()} admin1 regions, {DATE_START} to {DATE_END}",
    },
    "IPC": {
        "description": "Food security phase classifications by admin1",
        "vintage": (next(iter(ipc_data.values())).get("analysis_date", "unknown") if ipc_data else "unavailable"),
        "update_frequency": "Biannual",
        "coverage": f"{len(ipc_data)} regions" if ipc_data else "unavailable",
    },
    "CHIRPS": {
        "description": "Dekadal rainfall anomaly vs 1989–2018 baseline",
        "vintage": (next(iter(rainfall_data.values())).get("date", "unknown") if rainfall_data else "unavailable"),
        "update_frequency": "Dekadal (10-day)",
        "coverage": f"{len(rainfall_data)} regions" if rainfall_data else "unavailable",
    },
    "WorldPop/UNFPA": {
        "description": "Population projections by admin1 region",
        "vintage": "2021 projections",
        "update_frequency": "Annual",
        "coverage": f"{len(population_data)} regions" if population_data else "unavailable",
    },
    "IOM DTM / OCHA": {
        "description": "Harmonised IDP figures by admin1 region",
        "vintage": (next(iter(displacement_data.values())).get("reporting_date", "unknown") if displacement_data else "unavailable"),
        "update_frequency": "Irregular",
        "coverage": f"{len(displacement_data)} regions" if displacement_data else "unavailable",
    },
}

print("\n[5/6] Creating HTML brief...")
html_filename = f"somalia_brief_{REPORTING_PERIOD.lower().replace(' ', '_')}.html"
create_brief_html(brief_text, df, REPORTING_PERIOD, html_filename, monthly_baselines=monthly_baselines, current_month_start=CURRENT_MONTH_START, ipc_data=ipc_data, rainfall_data=rainfall_data, per_capita_data=per_capita_data, displacement_data=displacement_data, data_quality=data_quality)

print("\n[6/6] Saving data...")
df.to_csv("acled_data.csv", index=False)

metadata = {
    "reporting_period": REPORTING_PERIOD,
    "date_generated": datetime.now().isoformat(),
    "date_start": DATE_START,
    "date_end": DATE_END,
    "current_month_start": CURRENT_MONTH_START,
    "total_events": len(df),
    "reporting_month_events": len(df_march),
    "total_fatalities_reporting_month": int(df_march["fatalities"].sum()),
    "baseline_months": [{"label": m["label"], "events": len(m["df"])} for m in monthly_baselines],
    "ipc_data": {
        region: {
            "ipc_region": data["ipc_region"],
            "analysis_date": data["analysis_date"],
            "validity_from": data["validity_from"],
            "validity_to": data["validity_to"],
            "dominant_phase": data["dominant_phase"],
            "population_in_crisis": data["population_in_crisis"],
            "population_in_emergency": data["population_in_emergency"],
            "population_in_famine": data["population_in_famine"],
        }
        for region, data in ipc_data.items()
    },
    "rainfall_data": rainfall_data,
    "per_capita_data": per_capita_data,
    "displacement_data": displacement_data,
    "data_quality": data_quality,
}
with open("brief_metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

# Save current predictions for next month's review
watch_start = brief_text.find("[WHAT TO WATCH]")
watch_end = brief_text.find("[REFERENCES]") if "[REFERENCES]" in brief_text else len(brief_text)
if watch_start != -1:
    current_predictions = brief_text[watch_start + len("[WHAT TO WATCH]"):watch_end].strip()
    with open("previous_predictions.txt", "w") as f:
        f.write(f"Predictions from {REPORTING_PERIOD}:\n\n{current_predictions}")

print("\n" + "=" * 60)
print("PIPELINE COMPLETE")
print("=" * 60)
print(f"\nOutputs:")
print(f"  1. {docx_filename}")
print(f"  2. {html_filename}")
print(f"  3. brief_raw.txt")
print(f"  4. acled_data.csv")
print(f"\nOpen the HTML file: open {html_filename}")
