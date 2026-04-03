import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import re
st.set_page_config(
    page_title="Somalia Conflict Monitor",
    layout="wide",
    page_icon="🇸🇴"
)

# ============================================================
# DATA LOADING
# ============================================================

@st.cache_data
def load_data():
    df = pd.read_csv("acled_data.csv")
    df["fatalities"] = pd.to_numeric(df["fatalities"], errors="coerce").fillna(0).astype(int)
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["event_date"] = pd.to_datetime(df["event_date"])
    df = df.dropna(subset=["latitude", "longitude"])

    with open("brief_raw.txt", "r") as f:
        brief_text = f.read()

    with open("brief_metadata.json", "r") as f:
        metadata = json.load(f)

    return df, brief_text, metadata

df_full, brief_text, metadata = load_data()

reporting_period = metadata["reporting_period"]
current_month_start = pd.Timestamp(metadata.get("current_month_start", df_full["event_date"].max().replace(day=1)))
date_start = pd.Timestamp(metadata.get("date_start", df_full["event_date"].min()))
ipc_data = metadata.get("ipc_data", {})
rainfall_data = metadata.get("rainfall_data", {})
per_capita_data = metadata.get("per_capita_data", {})
displacement_data = metadata.get("displacement_data", {})
data_quality = metadata.get("data_quality", {})

df_reporting = df_full[df_full["event_date"] >= current_month_start].copy()

# Previous month data for trend indicators
prev_month_start = (current_month_start - pd.offsets.MonthBegin(1))
prev_month_end = current_month_start - pd.Timedelta(days=1)
df_prev = df_full[(df_full["event_date"] >= prev_month_start) & (df_full["event_date"] <= prev_month_end)]

# Try to get prev month events from baseline_months list first (more reliable)
baseline_months = metadata.get("baseline_months", [])
prev_month_label = prev_month_start.strftime("%B %Y")
prev_month_events_meta = next(
    (m["events"] for m in baseline_months if m["label"] == prev_month_label), None
)
prev_events = prev_month_events_meta if prev_month_events_meta is not None else len(df_prev)
prev_fatalities = int(df_prev["fatalities"].sum())

colour_map = {
    "Battles": "#c0392b",
    "Violence against civilians": "#e67e22",
    "Explosions/Remote violence": "#8e44ad",
    "Strategic developments": "#2980b9",
    "Protests": "#27ae60",
    "Riots": "#f39c12",
}

CHART_LABEL_MAP = {
    "Strategic developments": "Strategic developments*",
}

def chart_label(etype):
    return CHART_LABEL_MAP.get(etype, etype)

chart_colour_map = {chart_label(k): v for k, v in colour_map.items()}

# ============================================================
# BRIEF PARSING HELPERS  (needed early for executive summary)
# ============================================================

SECTION_MARKERS = [
    ("[OVERVIEW]", "Overview"),
    ("[FORECAST REVIEW]", "Forecast Review"),
    ("[DATA COVERAGE]", "Data Coverage"),
    ("[THEMATIC ANALYSIS]", "Thematic Analysis"),
    ("[GEOGRAPHIC FOCUS]", "Geographic Focus"),
    ("[TRENDS AND OUTLOOK]", "Trends And Outlook"),
    ("[WHAT TO WATCH]", "What To Watch"),
    ("[REFERENCES]", "References"),
]

def extract_sections(text):
    sections = {}
    for marker, title in SECTION_MARKERS:
        start = text.find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = len(text)
        for other_marker, _ in SECTION_MARKERS:
            if other_marker == marker:
                continue
            pos = text.find(other_marker, start)
            if pos != -1 and pos < end:
                end = pos
        sections[marker] = (title, text[start:end].strip())
    return sections

def format_brief_html(text):
    """Convert brief markup to HTML for safe rendering with styled comments."""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Comment blocks → blockquote style
    def _comment_block(m):
        inner = m.group(1).strip()
        return (
            '<div style="border-left:3px solid #b0bec5;padding:4px 12px;margin:8px 0 8px 0;'
            'color:#78909c;font-size:0.92em;font-style:italic;">'
            f'Comment: {inner}</div>'
        )
    text = re.sub(r'\[Comment:(.*?)\]', _comment_block, text, flags=re.DOTALL)
    # Assumption blocks → same style but slightly different shade
    def _assumption_block(m):
        inner = m.group(1).strip()
        return (
            '<div style="border-left:3px solid #b0bec5;padding:4px 12px;margin:8px 0 8px 0;'
            'color:#78909c;font-size:0.92em;font-style:italic;">'
            f'Assumption: {inner}</div>'
        )
    text = re.sub(r'\[Assumption:(.*?)\]', _assumption_block, text, flags=re.DOTALL)
    return text

sections = extract_sections(brief_text)

# ============================================================
# HEADER
# ============================================================

st.markdown(
    f"""
    <div style="background:#1a2332;padding:24px 32px;border-bottom:4px solid #c0392b;margin-bottom:24px;">
        <h1 style="color:#ecf0f1;font-size:22px;font-weight:700;letter-spacing:2px;
                   text-transform:uppercase;margin:0 0 4px 0;">Somalia Monthly Conflict Brief</h1>
        <div style="color:#95a5a6;font-size:14px;">Reporting period: {reporting_period}</div>
        <div style="color:#7f8c8d;font-size:11px;margin-top:4px;">
            Generated {metadata.get('date_generated','')[:10]} | Sources: ACLED, IPC, CHIRPS, WorldPop, IOM DTM
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# EXECUTIVE SUMMARY
# ============================================================

if "[OVERVIEW]" in sections:
    _, overview_text = sections["[OVERVIEW]"]
    st.markdown(
        f"""
        <div style="background:#f0f4f8;border-left:5px solid #c0392b;
                    border-radius:0 6px 6px 0;padding:16px 20px;margin-bottom:24px;">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                        letter-spacing:1px;color:#c0392b;margin-bottom:8px;">Executive Summary</div>
            <div style="font-size:14px;color:#2c3e50;line-height:1.6;">{overview_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# STAT CARDS
# ============================================================

total_reporting_events = metadata.get("reporting_month_events", len(df_reporting))
total_reporting_fatalities = metadata.get("total_fatalities_reporting_month", int(df_reporting["fatalities"].sum()))
regions_affected = df_reporting["admin1"].nunique()
total_dataset_events = metadata.get("total_events", len(df_full))

# Trend deltas
def _pct_delta(current, previous):
    if previous and previous > 0:
        pct = (current - previous) / previous * 100
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.0f}% from {prev_month_label.split()[0]}"
    return None

events_delta = _pct_delta(total_reporting_events, prev_events)
fatalities_delta = _pct_delta(total_reporting_fatalities, prev_fatalities)
regions_delta = _pct_delta(regions_affected, df_prev["admin1"].nunique())

# National per-capita conflict rate
national_percap = None
if per_capita_data:
    total_pop = sum(d.get("population", 0) for d in per_capita_data.values())
    if total_pop > 0:
        national_percap = total_reporting_events / total_pop * 100_000

# IPC Phase 3+ total
total_crisis = sum(v.get("population_in_crisis") or 0 for v in ipc_data.values()) if ipc_data else None

def _stat_card(number, label, delta=None, delta_positive_is_bad=True, accent="#c0392b", fmt="{:,}", delta_color=None):
    number_str = fmt.format(number) if isinstance(number, (int, float)) else str(number)
    if delta:
        if delta_color == "off":
            color = "#95a5a6"
        elif delta_positive_is_bad:
            color = "#c0392b" if delta.startswith("+") else "#27ae60"
        else:
            color = "#27ae60" if delta.startswith("+") else "#c0392b"
        delta_html = f'<div style="font-size:11px;color:{color};margin-top:2px;">{delta}</div>'
    elif delta_color == "off":
        # Invisible spacer so card height matches cards that have a delta
        delta_html = '<div style="font-size:11px;margin-top:2px;">&nbsp;</div>'
    else:
        delta_html = ""
    return f"""
    <div style="background:#fff;border-radius:6px;padding:16px;text-align:center;
                box-shadow:0 1px 4px rgba(0,0,0,0.08);border-top:3px solid {accent};">
        <div style="font-size:28px;font-weight:700;color:#1a2332;">{number_str}</div>
        <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;
                    letter-spacing:0.5px;margin-top:4px;">{label}</div>
        {delta_html}
    </div>
    """

col1, col2, col3, col4 = st.columns(4)
col1.markdown(_stat_card(total_reporting_events, f"Conflict events ({reporting_period})", events_delta), unsafe_allow_html=True)
col2.markdown(_stat_card(total_reporting_fatalities, f"Conflict fatalities ({reporting_period})", fatalities_delta), unsafe_allow_html=True)
col3.markdown(_stat_card(regions_affected, f"Regions affected ({reporting_period})", regions_delta), unsafe_allow_html=True)
col4.markdown(_stat_card(total_dataset_events, "Total events (12 months)", delta_color="off"), unsafe_allow_html=True)

st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

col5, col6 = st.columns(2)
if national_percap is not None:
    col5.markdown(
        _stat_card(national_percap, "Per-capita conflict rate (national avg, per 100k)", accent="#2980b9", fmt="{:.1f}"),
        unsafe_allow_html=True,
    )
if total_crisis is not None:
    col6.markdown(
        _stat_card(total_crisis, "IPC Phase 3+ population (crisis or worse)", accent="#e67e22"),
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

# ============================================================
# MAP — reporting month only
# ============================================================

st.markdown("### Conflict Event Map")

df_map = df_reporting.copy()
df_map["event_type_label"] = df_map["event_type"].map(chart_label)
df_map["size"] = (df_map["fatalities"] * 1.5 + 4).clip(upper=20)
df_map["event_date_str"] = df_map["event_date"].dt.strftime("%Y-%m-%d")

fig_map = px.scatter_mapbox(
    df_map,
    lat="latitude",
    lon="longitude",
    color="event_type_label",
    color_discrete_map=chart_colour_map,
    size="size",
    size_max=18,
    hover_name="location",
    hover_data={
        "admin1": True,
        "event_date_str": True,
        "event_type": True,
        "actor1": True,
        "fatalities": True,
        "event_type_label": False,
        "latitude": False,
        "longitude": False,
        "size": False,
    },
    labels={
        "admin1": "Region",
        "event_date_str": "Date",
        "event_type": "Type",
        "actor1": "Actor",
        "fatalities": "Fatalities",
        "event_type_label": "Event type",
    },
    zoom=5,
    center={"lat": 6.0, "lon": 46.2},
    mapbox_style="open-street-map",
    height=500,
)
fig_map.update_layout(
    margin={"r": 10, "t": 0, "l": 0, "b": 120},
    legend_title_text="Event type",
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.02,
        xanchor="center",
        x=0.5,
    ),
    annotations=[dict(
        text="*Strategic developments: non-violent events including troop movements,<br>territorial transfers, ceasefires and peace agreements.",
        xref="paper", yref="paper",
        x=0.5, y=-0.22,
        xanchor="center", yanchor="top",
        showarrow=False,
        font=dict(size=10, color="#7f8c8d"),
        align="center",
    )]
)
st.plotly_chart(fig_map, use_container_width=True)

# ============================================================
# ANALYTICAL BRIEF
# ============================================================

st.markdown("### Analytical Brief")

for marker, (title, content) in sections.items():
    if marker in ("[OVERVIEW]", "[REFERENCES]"):
        continue  # overview shown as executive summary; references shown after charts
    st.markdown(f"#### {title}")
    if marker == "[WHAT TO WATCH]":
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^[\d]+[\.\)]\s*", "", line)
            st.markdown(format_brief_html(line), unsafe_allow_html=True)
    else:
        for para in content.split("\n\n"):
            para = para.strip()
            if para:
                st.markdown(format_brief_html(para.replace("\n", " ")), unsafe_allow_html=True)
    st.markdown("---")

# ============================================================
# CHARTS (2x2)
# ============================================================

st.markdown("### Data Charts")
col_left, col_right = st.columns(2)

# Chart 1: Events by type per month — all months (line chart for readability at 36 months)
with col_left:
    month_starts_list = pd.date_range(start=date_start, end=df_full["event_date"].max(), freq="MS")
    n_months = len(month_starts_list)
    st.markdown(f"**Events By Type — Monthly Trend ({n_months} Months)**")
    type_rows = []
    for ms in month_starts_list:
        me = ms + pd.offsets.MonthEnd(1)
        subset = df_full[(df_full["event_date"] >= ms) & (df_full["event_date"] <= me)]
        lbl = ms.strftime("%b %y")
        for etype in colour_map:
            type_rows.append({"Month": lbl, "Type": chart_label(etype), "Count": int((subset["event_type"] == etype).sum())})
    df_type_month = pd.DataFrame(type_rows)
    month_order = [ms.strftime("%b %y") for ms in month_starts_list]
    fig1 = px.line(
        df_type_month, x="Month", y="Count", color="Type",
        color_discrete_map=chart_colour_map,
        height=320, markers=True,
        category_orders={"Month": month_order},
    )
    fig1.update_traces(marker={"size": 4})
    fig1.update_layout(
        margin={"t": 10, "b": 60},
        xaxis={"tickangle": -45, "tickfont": {"size": 9}},
        legend={"orientation": "h", "yanchor": "top", "y": -0.25, "xanchor": "center", "x": 0.5, "font": {"size": 10}},
    )
    st.plotly_chart(fig1, use_container_width=True)

# Chart 2: Events by actor — reporting month, top 10
with col_right:
    st.markdown(f"**Events By Actor — {reporting_period}**")
    actor_counts = df_reporting["actor1"].value_counts().head(10).reset_index()
    actor_counts.columns = ["Actor", "Count"]
    actor_counts["Actor"] = actor_counts["Actor"].str[:50]
    fig2 = px.bar(actor_counts, x="Count", y="Actor", orientation="h", height=320,
                  color_discrete_sequence=["#1a2332"])
    fig2.update_layout(margin={"t": 10, "b": 40, "l": 10}, yaxis={"autorange": "reversed"})
    st.plotly_chart(fig2, use_container_width=True)

col_left2, col_right2 = st.columns(2)

# Chart 3: Event type by region heatmap — reporting month
with col_left2:
    st.markdown(f"**Event Type By Region — {reporting_period}**")
    top_regions = df_reporting["admin1"].value_counts().head(10).index.tolist()
    etypes = list(colour_map.keys())
    etypes_labels = [chart_label(e) for e in etypes]
    heatmap_z = []
    for etype in etypes:
        row = [int(((df_reporting["admin1"] == r) & (df_reporting["event_type"] == etype)).sum())
               for r in top_regions]
        heatmap_z.append(row)
    fig3 = go.Figure(go.Heatmap(
        z=heatmap_z, x=top_regions, y=etypes_labels,
        colorscale=[[0, "#f5f6fa"], [0.5, "#e67e22"], [1, "#c0392b"]],
    ))
    fig3.update_layout(height=320, margin={"t": 10, "b": 80, "l": 180})
    st.plotly_chart(fig3, use_container_width=True)

# Chart 4: Events by region — reporting month
with col_right2:
    st.markdown(f"**Events By Region — {reporting_period}**")
    region_counts = df_reporting["admin1"].value_counts().head(10).reset_index()
    region_counts.columns = ["Region", "Count"]
    fig4 = px.bar(region_counts, x="Count", y="Region", orientation="h", height=320,
                  color_discrete_sequence=["#1a2332"])
    fig4.update_layout(margin={"t": 10, "b": 40}, yaxis={"autorange": "reversed"})
    st.plotly_chart(fig4, use_container_width=True)

# ============================================================
# IPC FOOD SECURITY
# ============================================================

if ipc_data:
    st.markdown("### Food Security (IPC)")
    sample = next(iter(ipc_data.values()))
    st.caption(
        f"IPC analysis date: {sample.get('analysis_date', 'unknown')} | "
        f"Validity: {sample.get('validity_from', '')} to {sample.get('validity_to', '')}. "
        "Phase 1=Minimal, 2=Stressed, 3=Crisis, 4=Emergency, 5=Famine."
    )

    total_emergency = sum(v.get("population_in_emergency") or 0 for v in ipc_data.values())

    col_ipc1, col_ipc2 = st.columns(2)
    for col, number, label in [
        (col_ipc1, total_crisis, "Phase 3+ (crisis or worse)"),
        (col_ipc2, total_emergency, "Phase 4+ (emergency or worse)"),
    ]:
        col.markdown(
            f"""
            <div style="background:#fff;border-radius:6px;padding:16px;text-align:center;
                        box-shadow:0 1px 4px rgba(0,0,0,0.08);border-top:3px solid #e67e22;">
                <div style="font-size:28px;font-weight:700;color:#1a2332;">{number:,}</div>
                <div style="font-size:11px;color:#7f8c8d;text-transform:uppercase;
                            letter-spacing:0.5px;margin-top:4px;">{label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

    ipc_rows = []
    for region, data in ipc_data.items():
        ipc_rows.append({
            "Region": region,
            "Phase 3+ (crisis)": data.get("population_in_crisis") or 0,
            "Phase 4+ (emergency)": data.get("population_in_emergency") or 0,
        })
    df_ipc = pd.DataFrame(ipc_rows).sort_values("Phase 3+ (crisis)", ascending=True)

    col_ipc_left, col_ipc_right = st.columns(2)

    with col_ipc_left:
        st.markdown("**Population In IPC Phase 3+ (Crisis Or Worse) By Region**")
        fig_ipc = go.Figure()
        fig_ipc.add_trace(go.Bar(
            x=df_ipc["Phase 3+ (crisis)"], y=df_ipc["Region"],
            orientation="h", name="Phase 3+", marker_color="#e67e22",
        ))
        fig_ipc.add_trace(go.Bar(
            x=df_ipc["Phase 4+ (emergency)"], y=df_ipc["Region"],
            orientation="h", name="Phase 4+", marker_color="#c0392b",
        ))
        fig_ipc.update_layout(
            barmode="overlay", height=400,
            margin={"t": 10, "b": 40, "l": 10},
            legend={"orientation": "h", "yanchor": "top", "y": -0.1, "xanchor": "center", "x": 0.5, "font": {"size": 10}},
        )
        st.plotly_chart(fig_ipc, use_container_width=True)

    with col_ipc_right:
        st.markdown("**IPC Phase By Region (Bubble Size = Phase 3+ Population)**")
        PHASE_COLORS = {
            "1": "#2ecc71", "2": "#f1c40f", "3": "#e67e22",
            "3+": "#e67e22", "4": "#c0392b", "5": "#7b241c",
        }
        centroids = df_full.groupby("admin1")[["latitude", "longitude"]].mean().reset_index()
        ipc_map_rows = []
        for _, row in centroids.iterrows():
            region = row["admin1"]
            if region in ipc_data:
                data = ipc_data[region]
                dominant = str(data.get("dominant_phase", "")) if data.get("dominant_phase") is not None else "n/a"
                ipc_map_rows.append({
                    "Region": region,
                    "Latitude": row["latitude"],
                    "Longitude": row["longitude"],
                    "Dominant phase": dominant,
                    "Phase 3+": data.get("population_in_crisis") or 0,
                    "Phase 4+": data.get("population_in_emergency") or 0,
                })
        if ipc_map_rows:
            df_ipc_map = pd.DataFrame(ipc_map_rows)
            phase_color_map = {k: v for k, v in PHASE_COLORS.items()}
            fig_ipc_map = px.scatter_mapbox(
                df_ipc_map,
                lat="Latitude", lon="Longitude",
                color="Dominant phase",
                color_discrete_map=phase_color_map,
                size="Phase 3+",
                size_max=30,
                hover_name="Region",
                hover_data={"Phase 3+": True, "Phase 4+": True, "Latitude": False, "Longitude": False},
                zoom=4, center={"lat": 6.0, "lon": 46.2},
                mapbox_style="open-street-map",
                height=400,
            )
            fig_ipc_map.update_layout(
                margin={"r": 0, "t": 0, "l": 0, "b": 60},
                legend_title_text="Dominant phase",
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.1,
                    xanchor="center",
                    x=0.5,
                ),
            )
            st.plotly_chart(fig_ipc_map, use_container_width=True)

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

# ============================================================
# RAINFALL (CHIRPS)
# ============================================================

if rainfall_data:
    st.markdown("### Rainfall Anomaly (CHIRPS)")
    sample_r = next(iter(rainfall_data.values()))
    version_note = " — forecast, not yet finalised" if sample_r.get("version") == "forecast" else ""
    st.caption(
        f"CHIRPS 3-month rainfall anomaly vs 1989–2018 baseline. "
        f"Dekad ending {sample_r.get('date', 'unknown')}{version_note}. "
        "Below 80% = drought. 80–95% = below average. 95–110% = normal. Above 110% = above average."
    )

    def _rain_color(r3q):
        if r3q is None: return "#95a5a6"
        if r3q < 60: return "#8b0000"
        if r3q < 80: return "#e74c3c"
        if r3q < 95: return "#e67e22"
        if r3q <= 110: return "#27ae60"
        if r3q <= 130: return "#3498db"
        return "#1a5276"

    rain_rows = []
    for region, data in rainfall_data.items():
        r3q = data.get("r3q") or 0
        rain_rows.append({
            "Region": region,
            "r3q": r3q,
            "Status": data.get("status", ""),
            "Color": _rain_color(data.get("r3q")),
        })
    df_rain = pd.DataFrame(rain_rows).sort_values("r3q", ascending=True)

    fig_rain = go.Figure(go.Bar(
        x=df_rain["r3q"],
        y=df_rain["Region"],
        orientation="h",
        marker_color=df_rain["Color"],
        hovertemplate="%{y}: %{x:.0f}% of normal<extra></extra>",
    ))
    fig_rain.add_vline(x=100, line_dash="dash", line_color="#2c3e50", line_width=1)
    fig_rain.update_layout(
        height=420,
        margin={"t": 10, "b": 40, "l": 10},
        xaxis_title="% of long-term average (100 = normal)",
    )
    st.plotly_chart(fig_rain, use_container_width=True)

# ============================================================
# PER-CAPITA CONFLICT RATES
# ============================================================

if per_capita_data:
    active_percap = {r: d for r, d in per_capita_data.items() if d.get("events", 0) > 0}
    if active_percap:
        st.markdown(f"### Per-Capita Conflict Rate — {reporting_period}")
        st.caption("Events per 100,000 population. Source: UNFPA 2021 population projections. Only regions with at least one event shown.")

        percap_rows = [
            {
                "Region": r,
                "Events per 100k": d["events_per_100k"],
                "Fatalities per 100k": d["fatalities_per_100k"],
                "Raw events": d["events"],
                "Population": d["population"],
            }
            for r, d in sorted(active_percap.items(), key=lambda x: x[1]["events_per_100k"], reverse=True)
        ]
        df_percap = pd.DataFrame(percap_rows)

        col_pc1, col_pc2 = st.columns(2)
        with col_pc1:
            st.markdown("**Events Per 100,000 Population**")
            fig_pc = px.bar(
                df_percap, x="Events per 100k", y="Region", orientation="h", height=380,
                color_discrete_sequence=["#1a2332"],
            )
            fig_pc.update_layout(margin={"t": 10, "b": 40, "l": 10}, yaxis={"autorange": "reversed"})
            st.plotly_chart(fig_pc, use_container_width=True)

        with col_pc2:
            st.markdown("**Raw Events Vs Per-Capita Rate**")
            fig_pc2 = px.scatter(
                df_percap, x="Raw events", y="Events per 100k", text="Region",
                height=380, color_discrete_sequence=["#c0392b"],
            )
            fig_pc2.update_traces(textposition="top center", textfont_size=9)
            fig_pc2.update_layout(margin={"t": 10, "b": 40})
            st.plotly_chart(fig_pc2, use_container_width=True)

# ============================================================
# DISPLACEMENT (IOM DTM)
# ============================================================

if displacement_data:
    active_disp = {r: d for r, d in displacement_data.items() if d.get("idps", 0) > 0}
    if active_disp:
        st.markdown("### IDP Displacement (IOM DTM)")
        sample_d = next(iter(displacement_data.values()))
        st.caption(
            f"Internally displaced persons (IDPs) by admin1 region. "
            f"Source: IOM DTM, reporting date {sample_d.get('reporting_date', 'unknown')}."
        )

        disp_rows = [
            {"Region": r, "IDPs": d["idps"]}
            for r, d in sorted(active_disp.items(), key=lambda x: x[1]["idps"], reverse=True)
        ]
        df_disp = pd.DataFrame(disp_rows)

        fig_disp = px.bar(
            df_disp, x="IDPs", y="Region", orientation="h", height=420,
            color_discrete_sequence=["#8e44ad"],
        )
        fig_disp.update_layout(margin={"t": 10, "b": 40, "l": 10}, yaxis={"autorange": "reversed"})
        st.plotly_chart(fig_disp, use_container_width=True)

# ============================================================
# DATA QUALITY
# ============================================================

if data_quality:
    st.markdown("### Data Quality")
    dq_rows = []
    for source, info in data_quality.items():
        dq_rows.append({
            "Source": source,
            "Description": info.get("description", ""),
            "Data vintage": info.get("vintage", ""),
            "Update frequency": info.get("update_frequency", ""),
            "Coverage": info.get("coverage", ""),
        })
    df_dq = pd.DataFrame(dq_rows)
    st.dataframe(df_dq, use_container_width=True, hide_index=True)

# ============================================================
# REFERENCES + EVENT VERIFICATION
# ============================================================

st.markdown("### References")

def _parse_ref(raw):
    raw = raw.strip()
    acled_ids = re.findall(r'SOM[\w-]+', raw)
    if acled_ids:
        return {"type": "acled", "ids": acled_ids, "raw": raw}
    rl = raw.lower()
    def _last_part(s):
        parts = s.split(",")
        return parts[-1].strip() if parts else ""
    if rl.startswith("ipc"):
        return {"type": "ipc", "region": _last_part(raw), "raw": raw}
    if "chirps" in rl:
        return {"type": "chirps", "region": _last_part(raw), "raw": raw}
    if any(k in rl for k in ("unfpa", "worldpop", "population estimate")):
        return {"type": "population", "region": _last_part(raw), "raw": raw}
    if any(k in rl for k in ("iom dtm", "harmonised idp", "idp figures")):
        return {"type": "displacement", "region": _last_part(raw), "raw": raw}
    return {"type": "other", "raw": raw}

with st.expander("Show references and event verification"):
    if "[REFERENCES]" in sections:
        _, ref_content = sections["[REFERENCES]"]
        for line in ref_content.split("\n"):
            line = line.strip()
            if line:
                st.markdown(f"`{line}`")
        st.markdown("---")

    st.caption("Spot-check claims in the analytical brief against raw ACLED event records.")
    ref_start = brief_text.find("[REFERENCES]")
    if ref_start == -1:
        st.info("No references section found in this brief.")
    else:
        ref_section = brief_text[ref_start + len("[REFERENCES]"):].strip()
        footnote_map = {}
        for line in ref_section.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^(\d+)[.\)]\s+(.+)$', line)
            if m:
                fn_num = int(m.group(1))
                footnote_map[fn_num] = _parse_ref(m.group(2))

        if not footnote_map:
            st.info("No references found in the references section.")
        else:
            col_ver1, col_ver2 = st.columns([2, 3])
            with col_ver1:
                selected_fn = st.selectbox(
                    "Select footnote",
                    options=sorted(footnote_map.keys()),
                    format_func=lambda n: f"Footnote {n} — {footnote_map[n]['raw'][:60]}",
                )

            if selected_fn is not None:
                ref = footnote_map[selected_fn]
                st.markdown(f"**Footnote {selected_fn}:** {ref['raw']}")

                if ref["type"] == "acled":
                    display_cols = [
                        "event_id_cnty", "event_date", "event_type", "sub_event_type",
                        "actor1", "actor2", "admin1", "admin2", "location", "fatalities",
                    ]
                    for eid in ref["ids"]:
                        mask = df_full["event_id_cnty"] == eid
                        if not mask.any():
                            mask = df_full["event_id_cnty"].str.replace("-", "", regex=False) == eid.replace("-", "")
                        if mask.any():
                            record = df_full[mask].iloc[0]
                            available = [c for c in display_cols if c in df_full.columns]
                            st.dataframe(record[available].to_frame().T, use_container_width=True, hide_index=True)
                            if "notes" in df_full.columns and pd.notna(record.get("notes", "")):
                                st.markdown(f"**Notes:** {record['notes']}")
                        else:
                            st.warning(f"Event ID `{eid}` not found in dataset.")

                elif ref["type"] == "ipc":
                    region = ref.get("region")
                    if region and region in ipc_data:
                        data = ipc_data[region]
                        st.json({
                            "region": region,
                            "analysis_date": data.get("analysis_date"),
                            "dominant_phase": data.get("dominant_phase"),
                            "population_in_crisis_phase3+": data.get("population_in_crisis"),
                            "population_in_emergency_phase4+": data.get("population_in_emergency"),
                            "validity": f"{data.get('validity_from')} to {data.get('validity_to')}",
                        })
                    else:
                        st.info("IPC reference — see the Food Security (IPC) section above.")

                elif ref["type"] == "chirps":
                    region = ref.get("region")
                    if region and region in rainfall_data:
                        data = rainfall_data[region]
                        st.json({
                            "region": region,
                            "date": data.get("date"),
                            "r3q_pct_of_normal": data.get("r3q"),
                            "status": data.get("status"),
                            "version": data.get("version"),
                        })
                    else:
                        st.info("CHIRPS reference — see the Rainfall Anomaly (CHIRPS) section above.")

                elif ref["type"] == "displacement":
                    region = ref.get("region")
                    if region and region in displacement_data:
                        data = displacement_data[region]
                        st.json({
                            "region": region,
                            "idps": data.get("idps"),
                            "reporting_date": data.get("reporting_date"),
                            "source": data.get("source"),
                        })
                    else:
                        st.info("Displacement reference — see the IDP Displacement section above.")

                elif ref["type"] == "population":
                    region = ref.get("region")
                    if region and region in per_capita_data:
                        data = per_capita_data[region]
                        st.json({
                            "region": region,
                            "population": data.get("population"),
                            "fatalities": data.get("fatalities"),
                            "fatalities_per_100k": data.get("fatalities_per_100k"),
                            "events": data.get("events"),
                            "events_per_100k": data.get("events_per_100k"),
                        })
                    else:
                        st.info("Population reference — see the Per-Capita Conflict Rate section above.")

                else:
                    st.info(f"Reference: {ref['raw']}")

# ============================================================
# METHODOLOGY
# ============================================================

st.markdown("### Methodology And Limitations")
with st.expander("Show methodology"):
    st.markdown("""
**Conflict data.** Armed Conflict Location and Event Data (ACLED). Updated weekly, accessed via API. Provides event-level conflict data for the reporting month and aggregate statistics for baseline months.

**Food security data.** IPC (Integrated Phase Classification) phase assessments, accessed via the IPC API. Provides population-level food security phase classifications by admin1 region.

**Rainfall data.** CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data) dekadal rainfall anomaly data, downloaded from HDX. Provides 3-month rainfall anomaly as a percentage of the 1989–2018 long-term average by admin1 region.

**Population data.** UNFPA 2021 population projections aggregated to admin1. Used to calculate per-capita conflict event and fatality rates.

**Displacement data.** Primary source: UNHCR/OCHA Harmonised IDP Figures (HDX), district figures from DTM and CCCM clusters aggregated to admin1. Supplemented by IOM DTM V3 API for regions not in the harmonised file. Figures are minimum estimates.

**Analytical process.** Reporting month event-level data is provided to a large language model (Claude, Anthropic) with all supplementary datasets and context notes. The model derives its own analytical conclusions from the data, constrained to what the data can support.

**Probability language.** Highly likely: 75–90%. Likely: 55–75%. Roughly even: 45–55%. Unlikely: 25–45%. Highly unlikely: 10–25%.

**Limitations.** No human source reporting, political intelligence or direct observation. ACLED subject to geographic reporting bias. Fatality figures are estimates. Rainfall and displacement data may lag real conditions. AI may produce plausible analysis not fully supported by data. All assessments require human review.
    """)
