import pandas as pd
import json
import re
from datetime import datetime


def create_brief_html(brief_text, df, reporting_period="March 2026",
                       output_path="somalia_brief.html", monthly_baselines=None, current_month_start=None,
                       ipc_data=None, rainfall_data=None, per_capita_data=None, displacement_data=None,
                       data_quality=None):
    """Create a standalone HTML file with brief, map and charts."""

    df = df.copy()
    df["fatalities"] = df["fatalities"].astype(int)
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)

    if current_month_start is None:
        current_month_start = df["event_date"].max()[:8] + "01"
    df_march = df[df["event_date"] >= current_month_start]

    if monthly_baselines is None:
        df_baseline = df[df["event_date"] < current_month_start]
        monthly_baselines = [{"label": "Baseline", "df": df_baseline}]

    # Map data (March only)
    map_data = df_march[["latitude", "longitude", "event_type", "location",
                          "admin1", "fatalities", "event_date", "actor1"]].to_dict("records")

    colour_map = {
        "Battles": "#c0392b",
        "Violence against civilians": "#e67e22",
        "Explosions/Remote violence": "#8e44ad",
        "Strategic developments": "#2980b9",
        "Protests": "#27ae60",
        "Riots": "#f39c12",
    }

    # Chart 1: Events by type per month (all months)
    def short_label(lbl):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(lbl, "%B %Y").strftime("%b %y")
        except ValueError:
            return lbl[:6]

    type_by_month = []
    all_chart_months = monthly_baselines + [{"label": reporting_period, "df": df_march}]
    for m in all_chart_months:
        slbl = short_label(m["label"])
        for etype in colour_map:
            count = len(m["df"][m["df"]["event_type"] == etype])
            type_by_month.append({"month": slbl, "type": etype, "count": count})

    # Chart 2: Events by actor (March, top 10) - truncate long names
    actor_counts = df_march["actor1"].value_counts().head(10)
    actor_data = [{"actor": a[:50], "count": int(c)} for a, c in actor_counts.items()]

    # Chart 3: Event type by region heatmap (March)
    regions_top = df_march["admin1"].value_counts().head(10).index.tolist()
    etypes = list(colour_map.keys())
    heatmap_z = []
    for etype in etypes:
        row = []
        for region in regions_top:
            count = len(df_march[(df_march["admin1"] == region) & (df_march["event_type"] == etype)])
            row.append(count)
        heatmap_z.append(row)

    # Chart 4: Events by region (March)
    region_counts = df_march["admin1"].value_counts().head(10)
    region_data = [{"region": r, "count": int(c)} for r, c in region_counts.items()]

    brief_html = format_brief_html(brief_text)

    # Data quality table HTML
    dq_html = ""
    if data_quality:
        rows_html = ""
        for source, info in data_quality.items():
            rows_html += (
                f'<tr><td style="font-weight:600;white-space:nowrap;">{source}</td>'
                f'<td>{info.get("description","")}</td>'
                f'<td style="white-space:nowrap;">{info.get("vintage","")}</td>'
                f'<td style="white-space:nowrap;">{info.get("update_frequency","")}</td>'
                f'<td>{info.get("coverage","")}</td></tr>\n'
            )
        dq_html = f"""
    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Data quality</div>
            <div class="card-body">
                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                    <thead>
                        <tr style="border-bottom:2px solid #1a2332;text-align:left;">
                            <th style="padding:6px 8px;">Source</th>
                            <th style="padding:6px 8px;">Description</th>
                            <th style="padding:6px 8px;">Data vintage</th>
                            <th style="padding:6px 8px;">Update frequency</th>
                            <th style="padding:6px 8px;">Coverage</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
"""

    # IPC chart data
    ipc_chart_data = []
    ipc_total_crisis = 0
    ipc_total_emergency = 0
    ipc_analysis_label = ""
    if ipc_data:
        for region, data in sorted(ipc_data.items(), key=lambda x: x[1].get("population_in_crisis") or 0):
            crisis = data.get("population_in_crisis") or 0
            emergency = data.get("population_in_emergency") or 0
            ipc_chart_data.append({"region": region, "crisis": crisis, "emergency": emergency})
            ipc_total_crisis += crisis
            ipc_total_emergency += emergency
        sample = next(iter(ipc_data.values()))
        ipc_analysis_label = (
            f"IPC analysis date: {sample.get('analysis_date', 'unknown')} | "
            f"Validity: {sample.get('validity_from', '')} to {sample.get('validity_to', '')}"
        )

    # Rainfall chart data
    rainfall_chart_data = []
    rainfall_label = ""
    if rainfall_data:
        def _rain_color(r3q):
            if r3q is None: return "#95a5a6"
            if r3q < 60: return "#8b0000"
            if r3q < 80: return "#e74c3c"
            if r3q < 95: return "#e67e22"
            if r3q <= 110: return "#27ae60"
            if r3q <= 130: return "#3498db"
            return "#1a5276"
        for region, data in sorted(rainfall_data.items(), key=lambda x: x[1].get("r3q") or 100):
            r3q = data.get("r3q") or 0
            rainfall_chart_data.append({
                "region": region,
                "r3q": r3q,
                "status": data.get("status", ""),
                "color": _rain_color(data.get("r3q")),
            })
        sample = next(iter(rainfall_data.values()))
        version_note = " (forecast)" if sample.get("version") == "forecast" else ""
        rainfall_label = f"CHIRPS dekad ending {sample.get('date', '')}{version_note}"

    # Per-capita chart data
    percap_chart_data = []
    if per_capita_data:
        for region, data in sorted(per_capita_data.items(),
                                    key=lambda x: x[1].get("events_per_100k", 0), reverse=True):
            if data.get("events", 0) > 0:
                percap_chart_data.append({
                    "region": region,
                    "events_per_100k": data.get("events_per_100k", 0),
                    "fatalities_per_100k": data.get("fatalities_per_100k", 0),
                })

    if ipc_data:
        ipc_js_block = (
            "var ipcData = " + json.dumps(ipc_chart_data) + ";\n"
            "Plotly.newPlot('chart-ipc', [\n"
            "    {x: ipcData.map(d => d.crisis), y: ipcData.map(d => d.region),\n"
            "     name: 'Phase 3+ (crisis)', type: 'bar', orientation: 'h',\n"
            "     marker: {color: '#e67e22'}},\n"
            "    {x: ipcData.map(d => d.emergency), y: ipcData.map(d => d.region),\n"
            "     name: 'Phase 4+ (emergency)', type: 'bar', orientation: 'h',\n"
            "     marker: {color: '#c0392b'}}\n"
            "], {\n"
            "    barmode: 'overlay', margin: {t: 10, b: 40, l: 140, r: 20}, height: 420,\n"
            "    font: {family: 'Segoe UI, Arial', size: 11},\n"
            "    xaxis: {title: 'Population'},\n"
            "    legend: {orientation: 'h', y: -0.15},\n"
            "    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'\n"
            "}, {responsive: true});"
        )
    else:
        ipc_js_block = ""

    if rainfall_chart_data:
        rainfall_js_block = (
            "var rainfallData = " + json.dumps(rainfall_chart_data) + ";\n"
            "Plotly.newPlot('chart-rainfall', [{\n"
            "    x: rainfallData.map(d => d.r3q),\n"
            "    y: rainfallData.map(d => d.region),\n"
            "    type: 'bar', orientation: 'h',\n"
            "    marker: {color: rainfallData.map(d => d.color)},\n"
            "    hovertemplate: '%{y}: %{x:.0f}% of normal<extra></extra>'\n"
            "}], {\n"
            "    shapes: [{type: 'line', x0: 100, x1: 100, y0: -0.5,\n"
            "               y1: rainfallData.length - 0.5, line: {color: '#2c3e50', dash: 'dash', width: 1}}],\n"
            "    margin: {t: 10, b: 50, l: 140, r: 20}, height: 420,\n"
            "    font: {family: 'Segoe UI, Arial', size: 11},\n"
            "    xaxis: {title: '% of long-term average (100 = normal)'},\n"
            "    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'\n"
            "}, {responsive: true});"
        )
    else:
        rainfall_js_block = ""

    if percap_chart_data:
        percap_js_block = (
            "var percapData = " + json.dumps(percap_chart_data) + ";\n"
            "Plotly.newPlot('chart-percap', [{\n"
            "    x: percapData.map(d => d.events_per_100k),\n"
            "    y: percapData.map(d => d.region),\n"
            "    name: 'Events per 100k', type: 'bar', orientation: 'h',\n"
            "    marker: {color: '#1a2332'}\n"
            "}], {\n"
            "    margin: {t: 10, b: 50, l: 140, r: 20}, height: 380,\n"
            "    font: {family: 'Segoe UI, Arial', size: 11},\n"
            "    xaxis: {title: 'Events per 100,000 population'},\n"
            "    yaxis: {autorange: 'reversed'},\n"
            "    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'\n"
            "}, {responsive: true});"
        )
    else:
        percap_js_block = ""

    # Displacement chart data
    displacement_chart_data = []
    displacement_label = ""
    if displacement_data:
        for region, data in sorted(displacement_data.items(),
                                   key=lambda x: x[1].get("idps", 0), reverse=True):
            idps = data.get("idps", 0)
            if idps > 0:
                displacement_chart_data.append({"region": region, "idps": idps})
        sample = next(iter(displacement_data.values()))
        displacement_label = f"IOM DTM reporting date: {sample.get('reporting_date', 'unknown')}"

    if displacement_chart_data:
        displacement_js_block = (
            "var dispData = " + json.dumps(displacement_chart_data) + ";\n"
            "Plotly.newPlot('chart-displacement', [{\n"
            "    x: dispData.map(d => d.idps),\n"
            "    y: dispData.map(d => d.region),\n"
            "    type: 'bar', orientation: 'h',\n"
            "    marker: {color: '#8e44ad'},\n"
            "    hovertemplate: '%{y}: %{x:,} IDPs<extra></extra>'\n"
            "}], {\n"
            "    margin: {t: 10, b: 50, l: 140, r: 20}, height: 420,\n"
            "    font: {family: 'Segoe UI, Arial', size: 11},\n"
            "    xaxis: {title: 'IDP individuals'},\n"
            "    yaxis: {autorange: 'reversed'},\n"
            "    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'\n"
            "}, {responsive: true});"
        )
    else:
        displacement_js_block = ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Somalia Monthly Conflict Brief - {reporting_period}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        background: #f5f6fa;
        color: #2c3e50;
        line-height: 1.6;
    }}
    .header {{
        background: #1a2332;
        color: #ecf0f1;
        padding: 32px 0;
        text-align: center;
        border-bottom: 4px solid #c0392b;
    }}
    .header h1 {{
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    .header .subtitle {{ font-size: 14px; color: #95a5a6; }}
    .header .meta {{ font-size: 11px; color: #7f8c8d; margin-top: 8px; }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    .grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
        margin-bottom: 24px;
    }}
    .grid-full {{ grid-column: 1 / -1; }}
    .card {{
        background: #fff;
        border-radius: 6px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        overflow: hidden;
    }}
    .card-header {{
        background: #1a2332;
        color: #ecf0f1;
        padding: 10px 16px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    .card-body {{ padding: 16px; }}
    #map {{ height: 450px; width: 100%; }}
    .brief-content {{ font-size: 13px; line-height: 1.7; }}
    .brief-content h2 {{
        font-size: 14px; font-weight: 700; text-transform: uppercase;
        color: #1a2332; margin-top: 20px; margin-bottom: 8px;
        padding-bottom: 4px; border-bottom: 2px solid #c0392b;
    }}
    .brief-content p {{ margin-bottom: 10px; }}
    .brief-content .comment {{ font-style: italic; color: #555; }}
    .brief-content .assumption {{ font-style: italic; color: #555; }}
    .brief-content .references {{
        font-size: 11px; color: #666; border-top: 1px solid #ddd;
        padding-top: 10px; margin-top: 16px;
    }}
    .watch-item {{
        margin-bottom: 8px; padding-left: 8px;
        border-left: 3px solid #c0392b;
    }}
    .stats-row {{
        display: grid; grid-template-columns: repeat(4, 1fr);
        gap: 16px; margin-bottom: 24px;
    }}
    .stat-card {{
        background: #fff; border-radius: 6px; padding: 16px;
        text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        border-top: 3px solid #c0392b;
    }}
    .stat-card .number {{ font-size: 28px; font-weight: 700; color: #1a2332; }}
    .stat-card .label {{
        font-size: 11px; color: #7f8c8d; text-transform: uppercase;
        letter-spacing: 0.5px; margin-top: 4px;
    }}
    .legend {{
        display: flex; flex-wrap: wrap; gap: 12px;
        padding: 8px 16px; font-size: 11px;
    }}
    .legend-item {{ display: flex; align-items: center; gap: 4px; }}
    .legend-dot {{
        width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    }}
    .footer {{
        text-align: center; padding: 24px; font-size: 11px;
        color: #95a5a6; border-top: 1px solid #e0e0e0; margin-top: 24px;
    }}
    .methodology {{ font-size: 12px; color: #555; line-height: 1.6; }}
    .methodology strong {{ color: #2c3e50; }}
    @media (max-width: 768px) {{
        .grid {{ grid-template-columns: 1fr; }}
        .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>Somalia Monthly Conflict Brief</h1>
    <div class="subtitle">Reporting period: {reporting_period}</div>
    <div class="meta">Generated {datetime.now().strftime("%d %B %Y")} | Sources: ACLED, IPC, CHIRPS, WorldPop, IOM DTM</div>
</div>

<div class="container">

    <div class="stats-row">
        <div class="stat-card">
            <div class="number">{len(df_march)}</div>
            <div class="label">Conflict events ({reporting_period})</div>
        </div>
        <div class="stat-card">
            <div class="number">{int(df_march["fatalities"].sum())}</div>
            <div class="label">Conflict fatalities ({reporting_period})</div>
        </div>
        <div class="stat-card">
            <div class="number">{len(df_march["admin1"].unique())}</div>
            <div class="label">Regions affected</div>
        </div>
        <div class="stat-card">
            <div class="number">{len(df)}</div>
            <div class="label">Events (Jan-Mar)</div>
        </div>
    </div>

    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Conflict event map - {reporting_period}</div>
            <div class="card-body" style="padding:0;">
                <div id="map"></div>
                <div class="legend">
                    {"".join(f'<div class="legend-item"><span class="legend-dot" style="background:{c}"></span>{t}</div>' for t, c in colour_map.items())}
                </div>
            </div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-header">Events by type — monthly trend ({len(all_chart_months)} months)</div>
            <div class="card-body"><div id="chart-type"></div></div>
        </div>
        <div class="card">
            <div class="card-header">Events by actor - {reporting_period}</div>
            <div class="card-body"><div id="chart-actor"></div></div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-header">Event type by region</div>
            <div class="card-body"><div id="chart-heatmap"></div></div>
        </div>
        <div class="card">
            <div class="card-header">Events by region - {reporting_period}</div>
            <div class="card-body"><div id="chart-region"></div></div>
        </div>
    </div>

    {"" if not ipc_data else f'''
    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Food security — IPC phase classifications</div>
            <div class="card-body">
                <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-bottom:16px;">
                    <div class="stat-card" style="border-top-color:#e67e22;">
                        <div class="number">{ipc_total_crisis:,}</div>
                        <div class="label">Phase 3+ (crisis or worse)</div>
                    </div>
                    <div class="stat-card" style="border-top-color:#c0392b;">
                        <div class="number">{ipc_total_emergency:,}</div>
                        <div class="label">Phase 4+ (emergency or worse)</div>
                    </div>
                </div>
                <p style="font-size:11px;color:#7f8c8d;margin-bottom:12px;">{ipc_analysis_label}. Phase 1=Minimal, 2=Stressed, 3=Crisis, 4=Emergency, 5=Famine.</p>
                <div id="chart-ipc"></div>
            </div>
        </div>
    </div>
    '''}

    {"" if not rainfall_chart_data else f'''
    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Rainfall anomaly (CHIRPS) — 3-month vs long-term average</div>
            <div class="card-body">
                <p style="font-size:11px;color:#7f8c8d;margin-bottom:12px;">{rainfall_label}. Red = drought (&lt;80%). Orange = below average (80–95%). Green = normal (95–110%). Blue = above average (&gt;110%). Dashed line = 100% (long-term average).</p>
                <div id="chart-rainfall"></div>
            </div>
        </div>
    </div>
    '''}

    {"" if not percap_chart_data else f'''
    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Per-capita conflict rate — events per 100,000 population ({reporting_period})</div>
            <div class="card-body">
                <p style="font-size:11px;color:#7f8c8d;margin-bottom:12px;">Source: UNFPA 2021 population projections. Only regions with at least one event shown.</p>
                <div id="chart-percap"></div>
            </div>
        </div>
    </div>
    '''}

    {"" if not displacement_chart_data else f'''
    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">IDP displacement by region (IOM DTM)</div>
            <div class="card-body">
                <p style="font-size:11px;color:#7f8c8d;margin-bottom:12px;">{displacement_label}. Internally displaced persons (IDPs) by admin1 region.</p>
                <div id="chart-displacement"></div>
            </div>
        </div>
    </div>
    '''}

    {dq_html}

    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Analytical brief</div>
            <div class="card-body brief-content">
                {brief_html}
            </div>
        </div>
    </div>

    <div class="grid">
        <div class="card grid-full">
            <div class="card-header">Methodology and limitations</div>
            <div class="card-body methodology">
                <details><summary>Show methodology</summary>
                <p><strong>Conflict data.</strong> Armed Conflict Location and Event Data (ACLED). Updated weekly, accessed via API. Provides event-level conflict data for the reporting month and aggregate statistics for baseline months.</p>
                <p><strong>Food security data.</strong> IPC (Integrated Phase Classification) phase assessments. Accessed via the IPC API. Provides population-level food security phase classifications by admin1 region.</p>
                <p><strong>Rainfall data.</strong> CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data) dekadal rainfall anomaly data. Downloaded from HDX. Provides 3-month rainfall anomaly as a percentage of the 1989–2018 long-term average by admin1 region.</p>
                <p><strong>Population data.</strong> UNFPA 2021 population projections, aggregated to admin1. Used to calculate per-capita conflict event and fatality rates for the reporting month.</p>
                <p><strong>Displacement data.</strong> Primary source: UNHCR/OCHA Harmonised IDP Figures (HDX), district-level figures consolidated from IOM DTM and CCCM cluster sources, aggregated to admin1. Regions absent from the harmonised file are supplemented with IOM DTM V3 API data. Figures are minimum estimates; coverage varies by region.</p>
                <p><strong>Analytical process.</strong> Event data for the reporting period and baseline months is processed programmatically. Reporting month event-level data is provided to a large language model (Claude, Anthropic) with all supplementary datasets and context notes on terminology and actor definitions. The model derives its own analytical conclusions from the data. Baseline months are provided as aggregate statistics only.</p>
                <p><strong>AI-generated content.</strong> The analytical narrative is AI-generated. The model derives its own conclusions from event data, constrained to what the data can support. Factual statements are distinguished from analytical commentary using [Comment: ...] blocks. Competing assumptions are presented for significant claims. ACLED event IDs are cited as footnote references.</p>
                <p><strong>Probability language.</strong> Highly likely: 75-90% probability. Likely: 55-75%. Roughly even: 45-55%. Unlikely: 25-45%. Highly unlikely: 10-25%. Tactical predictions (military and security patterns) may use the full scale. Political predictions default to "roughly even" because political outcomes depend on factors not captured in event data.</p>
                <p><strong>Limitations.</strong> No human source reporting, political intelligence or direct observation. ACLED subject to geographic reporting bias. Fatality figures are estimates. Rainfall and displacement data may lag real conditions. AI may produce plausible analysis not fully supported by data. All assessments require human review.</p>
                </details>
            </div>
        </div>
    </div>

</div>

<div class="footer">
    Somalia Conflict Monitor | Data: ACLED, IPC, CHIRPS, WorldPop, IOM DTM | Analysis: AI-generated (Claude, Anthropic) | {datetime.now().strftime("%d %B %Y")}
</div>

<script>
var map = L.map('map').setView([5.1, 46.2], 6);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}@2x.png', {{
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    maxZoom: 18
}}).addTo(map);

var colourMap = {json.dumps(colour_map)};
var events = {json.dumps(map_data)};

events.forEach(function(e) {{
    var colour = colourMap[e.event_type] || '#999';
    var radius = Math.max(3, Math.min(12, e.fatalities * 1.5 + 3));
    L.circleMarker([e.latitude, e.longitude], {{
        radius: radius, fillColor: colour, color: '#333',
        weight: 0.5, opacity: 0.8, fillOpacity: 0.6
    }}).addTo(map).bindPopup(
        '<strong>' + e.location + '</strong> (' + e.admin1 + ')<br>' +
        e.event_date + '<br>' + e.event_type + '<br>' +
        'Actor: ' + e.actor1 + '<br>Fatalities: ' + e.fatalities
    );
}});

// Events by type
var typeData = {json.dumps(type_by_month)};
var types = [...new Set(typeData.map(d => d.type))];
var months = [...new Set(typeData.map(d => d.month))];
Plotly.newPlot('chart-type', types.map(function(t) {{
    return {{
        x: months,
        y: months.map(m => {{ var i = typeData.find(d => d.month === m && d.type === t); return i ? i.count : 0; }}),
        name: t, type: 'scatter', mode: 'lines+markers',
        line: {{ color: colourMap[t] || '#999', width: 2 }},
        marker: {{ color: colourMap[t] || '#999', size: 4 }}
    }};
}}), {{
    margin: {{ t: 10, b: 70, l: 40, r: 10 }}, height: 320,
    font: {{ family: 'Segoe UI, Arial', size: 11 }},
    xaxis: {{ tickangle: -45, tickfont: {{ size: 9 }} }},
    legend: {{ orientation: 'h', y: -0.35, font: {{ size: 10 }} }},
    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'
}}, {{ responsive: true }});

// Events by actor
var actorData = {json.dumps(actor_data)};
Plotly.newPlot('chart-actor', [{{
    x: actorData.map(d => d.count),
    y: actorData.map(d => d.actor),
    type: 'bar', orientation: 'h', marker: {{ color: '#1a2332' }}
}}], {{
    margin: {{ t: 10, b: 40, l: 280, r: 20 }}, height: 350,
    font: {{ family: 'Segoe UI, Arial', size: 10 }},
    xaxis: {{ title: 'Events' }},
    yaxis: {{ automargin: true, tickfont: {{ size: 10 }} }},
    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'
}}, {{ responsive: true }});

// Event type by region heatmap
Plotly.newPlot('chart-heatmap', [{{
    z: {json.dumps(heatmap_z)},
    x: {json.dumps(regions_top)},
    y: {json.dumps(etypes)},
    type: 'heatmap',
    colorscale: [[0, '#f5f6fa'], [0.5, '#e67e22'], [1, '#c0392b']],
    showscale: true
}}], {{
    margin: {{ t: 10, b: 80, l: 180, r: 10 }}, height: 300,
    font: {{ family: 'Segoe UI, Arial', size: 10 }},
    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'
}}, {{ responsive: true }});

// IPC food security chart
{ipc_js_block}

// Rainfall anomaly chart
{rainfall_js_block}

// Per-capita conflict rate chart
{percap_js_block}

// IDP displacement chart
{displacement_js_block}

// Events by region
var regionData = {json.dumps(region_data)};
Plotly.newPlot('chart-region', [{{
    x: regionData.map(d => d.count),
    y: regionData.map(d => d.region),
    type: 'bar', orientation: 'h', marker: {{ color: '#1a2332' }}
}}], {{
    margin: {{ t: 10, b: 40, l: 120, r: 10 }}, height: 300,
    font: {{ family: 'Segoe UI, Arial', size: 11 }},
    xaxis: {{ title: 'Events' }},
    plot_bgcolor: 'rgba(0,0,0,0)', paper_bgcolor: 'rgba(0,0,0,0)'
}}, {{ responsive: true }});
</script>

</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"HTML brief saved: {output_path}")
    return output_path


def format_brief_html(text):
    """Convert the section-marked brief into HTML."""
    section_titles = {
        "[OVERVIEW]": "Overview",
        "[FORECAST REVIEW]": "Forecast review",
        "[DATA COVERAGE]": "Data coverage",
        "[THEMATIC ANALYSIS]": "Thematic analysis",
        "[GEOGRAPHIC FOCUS]": "Geographic focus",
        "[TRENDS AND OUTLOOK]": "Trends and outlook",
        "[WHAT TO WATCH]": "What to watch",
        "[REFERENCES]": "References",
    }

    html = ""
    for marker, title in section_titles.items():
        start = text.find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = len(text)
        for other_marker in section_titles:
            if other_marker == marker:
                continue
            pos = text.find(other_marker, start)
            if pos != -1 and pos < end:
                end = pos

        content = text[start:end].strip()

        if marker == "[REFERENCES]":
            html += f'<div class="references"><h2>{title}</h2>\n'
            html += '<details><summary>Show references</summary>\n'
            for line in content.split("\n"):
                line = line.strip()
                if line:
                    html += f"<p>{line}</p>\n"
            html += "</details>\n"
            html += "</div>\n"
            continue

        html += f"<h2>{title}</h2>\n"

        if marker == "[WHAT TO WATCH]":
            items = content.split("\n")
            for item in items:
                item = item.strip()
                if not item:
                    continue
                item = re.sub(r"^[\d]+[\.\)]\s*", "", item)
                item = re.sub(r"^[-\*\u2022]\s*", "", item)
                if item:
                    item = format_inline_html(item)
                    html += f'<div class="watch-item"><p>{item}</p></div>\n'
            continue

        paragraphs = content.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            match = re.match(r"\*\*(.+?)\*\*\s*(.*)", para, re.DOTALL)
            if match:
                heading = match.group(1).strip().rstrip(".")
                body = match.group(2).strip().replace("\n", " ")
                body = format_inline_html(body)
                if body:
                    html += f"<p><strong>{heading}.</strong> {body}</p>\n"
                else:
                    html += f"<p><strong>{heading}.</strong></p>\n"
            else:
                para_clean = para.replace("\n", " ")
                para_clean = format_inline_html(para_clean)
                html += f"<p>{para_clean}</p>\n"

    return html


def format_inline_html(text):
    """Format [Comment: ...], [Assumption: ...] and **bold** for HTML."""
    text = re.sub(
        r'\[Comment:(.*?)\]',
        r'<span class="comment">[Comment:\1]</span>',
        text, flags=re.DOTALL
    )
    text = re.sub(
        r'\[Assumption:(.*?)\]',
        r'<span class="assumption">[Assumption:\1]</span>',
        text, flags=re.DOTALL
    )
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return text


if __name__ == "__main__":
    print("format_html.py loaded successfully.")
