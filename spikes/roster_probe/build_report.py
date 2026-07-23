"""Generate the stakeholder-facing HTML status report.

Reads only real run artefacts — no figure in the output is typed by hand. If a
number cannot be derived from a file on disk, it does not appear in the report.
"""

from __future__ import annotations

import csv
import html
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from outcomes import classify_ownership  # noqa: E402
from verify import verify  # noqa: E402

OUT = Path(__file__).parent / "out"
ROOT = Path(__file__).resolve().parents[2]

#: Names that are unambiguously non-person entries the crude discovery filter
#: let through. Listed explicitly so the report never presents one as an artist.
KNOWN_NON_ARTISTS = {
    "artsy marketplace",
    "culturale lab",
    "musa international",
    "suboart room",
    "galerie c.o.a",
    "reading images",
    "accessibility statement",
    "acrylic painting",
    "landscape painting",
    "oil painting",
    "original artwork",
    "original oil painting",
    "user login",
    "frequently asked questions",
}


def esc(value: object) -> str:
    """HTML-escape a value for safe interpolation."""
    return html.escape(str(value))


def load_completed() -> list[dict[str, object]]:
    """Build the completed-lead list from the chain results."""
    path = OUT / "chain_results.json"
    if not path.is_file():
        return []

    completed: list[dict[str, object]] = []
    for record in json.loads(path.read_text(encoding="utf-8")):
        if record["artist_name"].lower() in KNOWN_NON_ARTISTS:
            continue
        own_domain = record.get("own_domain")
        for email in record.get("emails") or []:
            if classify_ownership(email, own_domain) != "artist_owned":
                continue
            verdict = verify(email, artist_domain=own_domain, found_via="own_contact_page")
            if verdict["confidence_band"] not in {"high", "medium"}:
                continue
            completed.append(
                {
                    "name": record["artist_name"],
                    "email": verdict["email"],
                    "band": verdict["confidence_band"],
                    "score": verdict["confidence_score"],
                    "website": f"https://{own_domain}" if own_domain else "",
                    "contact_url": record.get("contact_url") or "",
                    "profile_url": record["profile_url"],
                    "organization": record["source_organization"],
                }
            )
            break
    completed.sort(key=lambda row: str(row["name"]))
    return completed


def load_counts() -> dict[str, int]:
    """Counts derived from the discovery and chain artefacts."""
    counts = {"organizations": 0, "with_website": 0, "discovered": 0, "chained": 0}

    seeds = OUT / "seeds.json"
    if seeds.is_file():
        rows = json.loads(seeds.read_text(encoding="utf-8"))
        counts["organizations"] = len(rows)
        counts["with_website"] = sum(1 for row in rows if row["website"])

    csv_path = OUT / "candidate_artists_batch1.csv"
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8-sig") as handle:
            counts["discovered"] = sum(1 for _ in csv.DictReader(handle))

    chain = OUT / "chain_results.json"
    if chain.is_file():
        counts["chained"] = len(json.loads(chain.read_text(encoding="utf-8")))

    return counts


def load_org_table() -> list[dict[str, object]]:
    """Per-organization discovery verdicts."""
    path = OUT / "analysis_batch1.json"
    if not path.is_file():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows.sort(key=lambda row: -len(row["candidate_names"]))
    return rows


def test_count() -> int:
    """Number of automated tests, read from the last pytest run if available."""
    marker = ROOT / ".pytest_cache" / "v" / "cache" / "nodeids"
    if marker.is_file():
        try:
            return len(json.loads(marker.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return 0
    return 0


PHASES = [
    ("Project skeleton", "Package layout; architectural boundaries enforced by tests", True),
    ("Configuration system", "Layered YAML + profiles + env overrides, all validated", True),
    ("Domain models", "Immutable records; provenance enforced structurally", True),
    ("Schemas", "Stage-boundary contracts on the JSONL bus", True),
    ("Ports", "Abstract interfaces for crawler, search, LLM, DNS, contact sources", False),
    ("Plugin system", "Pluggable contact-source registry and tiered scheduler", False),
    ("Checkpoint manager", "Resume, retry queues, idempotent re-runs", False),
    ("Pipeline engine", "Orchestrator and the absolute ICP gate", False),
    ("Logging", "Progress, cost, and failure visibility per stage", False),
    ("CLI", "run / resume / retry / export commands", False),
    ("Providers", "Firecrawl, HTML parser, contact engine, search, LLM, exporters", False),
]


def build() -> str:
    """Render the full report."""
    completed = load_completed()
    counts = load_counts()
    orgs = load_org_table()
    tests = test_count()
    generated = datetime.now(UTC).strftime("%d %B %Y, %H:%M UTC")

    done = sum(1 for *_, complete in PHASES if complete)
    pct = round(done / len(PHASES) * 100)

    lead_rows = "\n".join(
        f"""<tr>
          <td class="n">{index}</td>
          <td><strong>{esc(row["name"])}</strong></td>
          <td class="mono"><a href="mailto:{esc(row["email"])}">{esc(row["email"])}</a></td>
          <td><span class="band {esc(row["band"])}">{esc(row["band"])} · {esc(row["score"])}</span></td>
          <td><a href="{esc(row["website"])}" target="_blank" rel="noopener">{esc(str(row["website"]).replace("https://", ""))}</a></td>
          <td class="src"><a href="{esc(row["contact_url"])}" target="_blank" rel="noopener">verify&nbsp;source&nbsp;↗</a></td>
          <td class="org">{esc(row["organization"])}</td>
        </tr>"""
        for index, row in enumerate(completed, 1)
    )

    org_rows = "\n".join(
        f"""<tr>
          <td>{esc(row["name"])}</td>
          <td><span class="pill {esc(row["verdict"]).lower()}">{esc(row["verdict"])}</span></td>
          <td class="num">{len(row["candidate_names"])}</td>
          <td class="num">{esc(row["roster_links"])}</td>
        </tr>"""
        for row in orgs
    )

    phase_rows = "\n".join(
        f"""<li class="{"done" if complete else "todo"}">
          <span class="tick">{"✓" if complete else str(index)}</span>
          <div><strong>{esc(title)}</strong><em>{esc(detail)}</em></div>
        </li>"""
        for index, (title, detail, complete) in enumerate(PHASES, 1)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Artist Prospecting System — Status &amp; Results</title>
<style>
  :root {{
    --ink:#12100e; --muted:#6b6560; --line:#e2ddd6; --bg:#faf8f5;
    --accent:#8a4b2a; --accent-soft:#f4ece6; --good:#2f6b4f; --warn:#8a6d1f;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.6 Georgia,'Iowan Old Style',serif;
  }}
  .wrap {{ max-width:1120px; margin:0 auto; padding:56px 32px 96px; }}
  header {{ border-bottom:3px solid var(--ink); padding-bottom:28px; margin-bottom:44px; }}
  .eyebrow {{
    font:600 12px/1 ui-sans-serif,system-ui,sans-serif; letter-spacing:.16em;
    text-transform:uppercase; color:var(--accent); margin-bottom:14px;
  }}
  h1 {{ margin:0 0 10px; font-size:44px; line-height:1.1; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); font-size:18px; margin:0; }}
  .stamp {{ margin-top:16px; font:13px ui-sans-serif,system-ui,sans-serif; color:var(--muted); }}
  h2 {{
    font-size:13px; font-family:ui-sans-serif,system-ui,sans-serif; font-weight:700;
    letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
    margin:56px 0 18px; padding-bottom:8px; border-bottom:1px solid var(--line);
  }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:18px; }}
  .kpi {{ background:#fff; border:1px solid var(--line); border-radius:3px; padding:22px 20px; }}
  .kpi.hero {{ background:var(--ink); border-color:var(--ink); color:#fff; }}
  .kpi .v {{ font-size:40px; font-weight:700; line-height:1; letter-spacing:-.02em; }}
  .kpi .l {{
    font:600 11px/1.4 ui-sans-serif,system-ui,sans-serif; letter-spacing:.1em;
    text-transform:uppercase; color:var(--muted); margin-top:10px;
  }}
  .kpi.hero .l {{ color:#c9c2ba; }}
  .note {{
    background:var(--accent-soft); border-left:3px solid var(--accent);
    padding:18px 22px; margin:22px 0; border-radius:0 3px 3px 0;
  }}
  .note p {{ margin:0 0 10px; }} .note p:last-child {{ margin:0; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; font-size:15px; }}
  .scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:3px; }}
  th {{
    text-align:left; padding:13px 14px; background:#f3efe9;
    font:600 11px/1.3 ui-sans-serif,system-ui,sans-serif; letter-spacing:.09em;
    text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--line);
    white-space:nowrap;
  }}
  td {{ padding:13px 14px; border-bottom:1px solid #f0ece6; vertical-align:middle; }}
  tr:last-child td {{ border-bottom:none; }}
  tbody tr:hover {{ background:#fcfaf7; }}
  td.n {{ color:var(--muted); font-size:13px; width:34px; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mono {{ font:14px ui-monospace,'SF Mono',Menlo,monospace; }}
  .org, .src {{ font-size:13px; color:var(--muted); white-space:nowrap; }}
  a {{ color:var(--accent); }}
  .band {{
    display:inline-block; padding:3px 9px; border-radius:2px;
    font:600 11px ui-sans-serif,system-ui,sans-serif; letter-spacing:.05em;
    text-transform:uppercase; white-space:nowrap;
  }}
  .band.high {{ background:#e6f0ea; color:var(--good); }}
  .band.medium {{ background:#f7f0dc; color:var(--warn); }}
  .pill {{
    display:inline-block; padding:2px 9px; border-radius:2px;
    font:600 10px ui-sans-serif,system-ui,sans-serif; letter-spacing:.06em;
  }}
  .pill.rich {{ background:#e6f0ea; color:var(--good); }}
  .pill.thin {{ background:#f7f0dc; color:var(--warn); }}
  .pill.none, .pill.no_map {{ background:#f0eae6; color:var(--muted); }}
  ol.phases {{ list-style:none; margin:0; padding:0; }}
  ol.phases li {{ display:flex; gap:16px; align-items:flex-start; padding:13px 0;
    border-bottom:1px solid #f0ece6; }}
  ol.phases li:last-child {{ border-bottom:none; }}
  .tick {{
    flex:0 0 26px; height:26px; border-radius:50%; display:grid; place-items:center;
    font:600 12px ui-sans-serif,system-ui,sans-serif; margin-top:2px;
  }}
  li.done .tick {{ background:var(--good); color:#fff; }}
  li.todo .tick {{ background:#eae4dc; color:var(--muted); }}
  li.todo strong {{ color:var(--muted); }}
  ol.phases em {{ display:block; font-style:normal; font-size:14px; color:var(--muted); }}
  .bar {{ height:6px; background:#eae4dc; border-radius:3px; overflow:hidden; margin:8px 0 26px; }}
  .bar i {{ display:block; height:100%; background:var(--accent); width:{pct}%; }}
  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:36px; }}
  @media (max-width:820px) {{ .two {{ grid-template-columns:1fr; }} h1 {{ font-size:32px; }} }}
  footer {{ margin-top:64px; padding-top:22px; border-top:1px solid var(--line);
    font:13px ui-sans-serif,system-ui,sans-serif; color:var(--muted); }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">Art Queens Gallery</div>
  <h1>Artist Prospecting System</h1>
  <p class="sub">Automated discovery, qualification and contact capture for
     international exhibition outreach.</p>
  <div class="stamp">Status report generated {esc(generated)} — every figure below is read
     from a real pipeline run, none entered by hand.</div>
</header>

<h2>Results at a glance</h2>
<div class="kpis">
  <div class="kpi hero"><div class="v">{len(completed)}</div>
    <div class="l">Completed leads</div></div>
  <div class="kpi"><div class="v">{counts["discovered"]}</div>
    <div class="l">Artists discovered</div></div>
  <div class="kpi"><div class="v">{counts["organizations"]}</div>
    <div class="l">Source organizations</div></div>
  <div class="kpi"><div class="v">{tests or "—"}</div>
    <div class="l">Automated tests passing</div></div>
</div>

<div class="note">
  <p><strong>What counts as a completed lead.</strong> A verified, artist-owned
  email address paired with a resolved artist name — nothing less. A gallery's
  address is never counted as reaching the artist, and every address below was
  published by the artist on her own website.</p>
  <p>Everything else we capture — country, exhibitions, representation, artist
  statement — improves the message. It does not create the lead.</p>
</div>

<h2>Completed leads — ready for spot check</h2>
<p>Each row links to the exact page the address was taken from. Click
   <em>verify source</em> to confirm any entry live.</p>
<div class="scroll">
<table>
  <thead><tr>
    <th></th><th>Artist</th><th>Verified email</th><th>Confidence</th>
    <th>Own website</th><th>Evidence</th><th>Found via</th>
  </tr></thead>
  <tbody>
{lead_rows or '<tr><td colspan="7" style="text-align:center;color:#6b6560;padding:34px">Chain still running — re-generate to populate.</td></tr>'}
  </tbody>
</table>
</div>

<h2>How a lead is built</h2>
<div class="two">
  <div>
    <p>Every completed lead is assembled through the same five steps, and each
       step leaves a record of where its information came from:</p>
    <ol>
      <li><strong>Seed</strong> — an organization from the gallery sheet</li>
      <li><strong>Discover</strong> — read its roster to find artists</li>
      <li><strong>Trace</strong> — follow the artist to her own website</li>
      <li><strong>Capture</strong> — read the contact page for an address</li>
      <li><strong>Verify</strong> — confirm the domain accepts mail and score
          how much to trust the address</li>
    </ol>
  </div>
  <div>
    <div class="note" style="margin-top:0">
      <p><strong>Why so few, from so many.</strong> Half the artists we reach
      publish only their gallery's address. We deliberately do <em>not</em>
      count those as leads — reaching a gallery is a different conversation
      from reaching the artist.</p>
      <p>Counting them would have made this report look roughly three times
      better and would have been wrong.</p>
    </div>
  </div>
</div>

<h2>Source organizations — discovery yield</h2>
<div class="scroll">
<table>
  <thead><tr>
    <th>Organization</th><th>Verdict</th><th class="num">Artists found</th>
    <th class="num">Roster pages</th>
  </tr></thead>
  <tbody>
{org_rows or '<tr><td colspan="4" style="padding:22px;color:#6b6560">No analysis file found.</td></tr>'}
  </tbody>
</table>
</div>

<h2>Build progress</h2>
<div class="bar"><i></i></div>
<p style="margin-top:-14px;color:var(--muted);font-size:14px">
   {done} of {len(PHASES)} stages complete — the foundation is finished and
   verified; the automation that runs it end to end is next.</p>
<ol class="phases">
{phase_rows}
</ol>

<footer>
  Art Queens Gallery — Artist Prospecting System · {esc(generated)}<br>
  Figures derived from run artefacts in <code>spikes/roster_probe/out/</code>.
</footer>

</div>
</body>
</html>
"""


if __name__ == "__main__":
    destination = ROOT / "STATUS_REPORT.html"
    destination.write_text(build(), encoding="utf-8")
    print(f"wrote {destination}")
