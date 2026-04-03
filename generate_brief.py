import requests
import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv
import os

# Load credentials
load_dotenv()
email = os.getenv("ACLED_EMAIL")
password = os.getenv("ACLED_PASSWORD")
anthropic_key = os.getenv("ANTHROPIC_API_KEY")

# Step 1: Authenticate with ACLED
print("Authenticating with ACLED...")
auth_response = requests.post(
    "https://acleddata.com/oauth/token",
    data={
        "username": email,
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

# Step 2: Pull Somalia conflict data (3 months for baseline)
print("Fetching Somalia conflict data...")
response = requests.get(
    "https://acleddata.com/api/acled/read",
    headers={"Authorization": f"Bearer {access_token}"},
    params={
        "country": "Somalia",
        "event_date": "2026-01-01|2026-03-31",
        "event_date_where": "BETWEEN",
        "limit": 5000
    }
)

if response.status_code != 200:
    print(f"Data request failed: {response.status_code}")
    print(response.text)
    exit()

data = response.json()["data"]
df = pd.DataFrame(data)
df["fatalities"] = df["fatalities"].astype(int)
print(f"Pulled {len(df)} events (Jan - Mar 2026).")

# Step 3: Split data into reporting period and baseline
df_march = df[df["event_date"] >= "2026-03-01"].copy()
df_baseline = df[df["event_date"] < "2026-03-01"].copy()

print(f"March 2026: {len(df_march)} events")
print(f"Baseline (Jan-Feb): {len(df_baseline)} events")

# Step 4: Prepare March event data for Claude
summary_cols = [
    "event_id_cnty", "event_date", "event_type", "sub_event_type",
    "actor1", "actor2", "admin1", "admin2",
    "location", "fatalities", "notes"
]
march_csv = df_march[summary_cols].to_csv(index=False)

# Step 5: Generate baseline statistics summary
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

df_jan = df_baseline[df_baseline["event_date"] < "2026-02-01"]
df_feb = df_baseline[df_baseline["event_date"] >= "2026-02-01"]

baseline_text = monthly_summary(df_jan, "January 2026")
baseline_text += "\n\n" + monthly_summary(df_feb, "February 2026")
baseline_text += "\n\n" + monthly_summary(df_march, "March 2026 (reporting period)")

# Step 6: Generate analytical brief
print("Generating analytical brief...")

system_prompt = """You are a senior conflict analyst producing a monthly intelligence brief on Somalia for a Humanitarian Country Team principal. Write as an opinionated, evidence-based analyst, not a reporter. Your consumer is a senior decision-maker who knows Somalia well. Do not explain basic context they already understand.

CRITICAL INSTRUCTION - REPORTING PERIOD:
The reporting period is March 2026 ONLY. You will receive:
1. Full event-level data for March 2026 only. Base your analysis on this data.
2. Statistical summaries of January and February 2026 for trend comparison.
You do NOT have event-level data for January or February. Do not reference specific January or February events, event IDs, locations or actors. You may only reference January and February through their aggregate statistics (event counts, fatality totals, regional distributions) when making month-on-month comparisons.

STRUCTURE:
1. BLUF (Bottom Line Up Front): One paragraph, three to four sentences maximum. State the single most important development or shift in March 2026 and its operational implication. Do not summarise the entire brief.
2. Data coverage note: One to two sentences noting the total number of March events, and any visible geographic concentration that may reflect reporting access rather than actual conflict intensity. ACLED data is subject to reporting bias: events in Mogadishu and major towns are more likely to be captured than events in remote or al-Shabaab-controlled areas.
3. Thematic analysis: Organise by theme, not geography. Select themes based on what March data shows. Do not force categories where the data is thin.
4. Geographic focus: Highlight two or three regions that warrant specific attention in March. This section must add new insight not already covered in the thematic analysis. Focus on operational or access implications specific to the location. If a region was adequately covered in the thematic section, choose a different region or angle.
5. Trends and outlook: Identify trends by comparing March statistics against January and February baselines. Draw analytical conclusions and flag them clearly as analytical judgments.
6. What to watch: Three to five specific, observable indicators the consumer should monitor in April. Each indicator must name a specific actor, location or threshold.

PROBABILITY LANGUAGE:
When making predictive judgments about what will happen in the next reporting period, use these terms with the percentage range in parentheses:
   - Highly likely (75-90%)
   - Likely (55-75%)
   - Roughly even (45-55%)
   - Unlikely (25-45%)
   - Highly unlikely (10-25%)
Never use "almost certain" or "remote". Always state the observable basis for the judgment. Always include the percentage range in parentheses after the probability term.
Not every forward-looking statement requires a probability. Describing an observable trend does not need a probability term. Probability language is required only when making a predictive judgment about what will happen next.

STYLE:
- British English. Active voice. Short sentences and paragraphs.
- Lead with the answer, then provide the evidence.
- No em dashes. Use full stops or commas instead.
- No Oxford comma.
- 600-800 words total. Every sentence must earn its place.
- Translate ACLED actor codes into natural analytical language (e.g. "SNA forces" not "Military Forces of Somalia (2022-)").

ANALYTICAL DISCIPLINE:

Evidence and attribution:
- For every significant claim, cite the ACLED event ID(s) that support it in parentheses, e.g. (SOM47399, SOM47412). You may only cite event IDs from March 2026 data.
- You MUST explicitly label observations, inferences and assumptions throughout the brief. Use these exact phrases:
  * "The data shows..." for observable facts drawn directly from the dataset.
  * "I infer..." for analytical conclusions drawn from the data.
  * "This assumes..." for underlying assumptions that could be wrong.
  Every paragraph in the thematic analysis and trends sections must contain at least one of these phrases. This is non-negotiable.
- Do not present inferences as established facts.
- Do not include any detail, event or statistic that is not explicitly present in the data provided. Do not add details from your own training data.
- If the data is insufficient to support a conclusion, say so explicitly.

Competing assumptions:
- When a significant development could plausibly be explained by more than one cause or motivation, you MUST present competing assumptions. State the primary assumption and at least one alternative reading.
- Apply this to every "This assumes..." statement. Ask: what is the alternative explanation? State it.
- The consumer should see which interpretation you favour and why, but also understand other readings exist.

Fatality figures:
- ACLED fatality figures are often estimates, sometimes from single sources. Present them as approximate: "approximately 40" or "at least 12", not as precise counts.

BANNED PHRASES - do not use any of these:
"unprecedented", "the most significant", "the most important", "the deadliest", "the worst", "the highest", "the largest", "the first time", "never before", "historic", "most lethal", "most serious", "most critical", "most notable", "most concerning". Do not use any superlative that implies knowledge beyond three months of data. Comparative claims are permitted only between months in the dataset using specific numbers.

Probability calibration:
- You are working from ACLED event data alone. No human source reporting, no political intelligence, no direct observation. Calibrate accordingly.
- Default to one tier lower than your instinct.
- Reserve "highly likely (75-90%)" for patterns supported by large numbers of consistent events across the full dataset.

Somalia-specific checks:
- Do not conflate al-Shabaab operational behaviour (attacks, ambushes, IEDs) with governance behaviour (taxation, court rulings, service provision) or political mobilisation (organised protests, rallies). Three distinct categories.
- Do not project rational-actor or Western institutional logic onto clan-based decision-making.
- Do not assume Mogadishu-based reporting is representative of conditions in southern and central regions.
- Apply scepticism to official transition timelines.
- Only reference seasonal or climate factors if mentioned in the ACLED notes field.
- Do not over-interpret single events. Look for patterns.

FORMAT YOUR RESPONSE WITH THESE SECTION MARKERS:
[BLUF]
[DATA COVERAGE]
[THEMATIC ANALYSIS]
[GEOGRAPHIC FOCUS]
[TRENDS AND OUTLOOK]
[WHAT TO WATCH]

Use these exact markers at the start of each section so the output can be parsed programmatically."""

user_message = f"""Produce the monthly intelligence brief for Somalia. The REPORTING PERIOD is March 2026.

MARCH 2026 EVENT DATA (full event-level detail):
{march_csv}

BASELINE STATISTICAL SUMMARIES (for trend comparison only - no event-level detail):
{baseline_text}"""

client = Anthropic(api_key=anthropic_key)
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2000,
    system=system_prompt,
    messages=[
        {"role": "user", "content": user_message}
    ]
)

brief = response.content[0].text

print("\n" + "=" * 60)
print("SOMALIA MONTHLY CONFLICT BRIEF")
print("Reporting period: March 2026")
print("=" * 60)
print(brief)
