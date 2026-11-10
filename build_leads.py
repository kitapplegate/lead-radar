#!/usr/bin/env python3
"""Build leads.json for Lead Radar. Public business fields only. Scores via TypeSafe Jev."""
from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://api.typesafe.ai/v1/systemone"
STILLWATER = (36.1156, -97.0584)
BATCH = 10
EST_USD_PER_TOKEN = 6e-8  # illustrative fallback from Two14 jev_lib

REASON_LABELS = {
    "local_lab": "Local accredited lab with recurring chain-of-custody and reporting paperwork",
    "spill_osro": "Independent spill response firm with HAZWOPER and incident report burden",
    "oilfield_small": "Small oilfield contractor with JSA, ISN, and crew paperwork",
    "water_dmr": "Private water or wastewater operator with monthly DMRs and operator logs",
    "hazmat_fleet": "Hazmat trucking fleet with DQ files and hazmat training records",
    "waste_hauler": "Waste hauler with manifests and DOT compliance paperwork",
    "ag_chem": "Ag chemical dealer with applicator records and hazmat transport docs",
    "too_big": "Looks too large or corporate for a first Marzipan wedge",
    "gov": "Government or municipal buyer with slow procurement",
    "thin_signal": "Thin public signal; worth a light research pass",
}

FIT_CRITERIA = [
    "Poor fit: chain, government, or already has strong in-house compliance IT",
    "Weak fit: regulated but large or corporate-owned",
    "Moderate fit: small regulated firm with mixed signals",
    "Strong fit: small local regulated firm with recurring paperwork",
    "Excellent fit: small local regulated firm, heavy reporting, no IT staff likely",
]

INDUSTRY_MAP = {
    "Spill Response": "Spill Response",
    "Environmental Labs": "Environmental Labs",
    "Oilfield Services": "Oilfield Services",
    "Water and Wastewater": "Water and Wastewater",
    "Hazmat Trucking": "Hazmat Trucking",
    "Waste Haulers": "Waste Haulers",
    "Ag Chemical Dealers": "Ag Chemical Dealers",
}

NEXT_TEMPLATES = {
    "Spill Response": (
        "Look up their OSRO or spill response page and note one recurring report they already file.",
        "Draft a short note asking how they currently handle post-incident write-ups. Review before sending.",
    ),
    "Environmental Labs": (
        "Skim their accreditation or services page for chain-of-custody and reporting language.",
        "Draft a note offering a sample intake-to-report checklist. Review before sending.",
    ),
    "Oilfield Services": (
        "Check for ISNetworld or Avetta mentions and estimate crew paperwork load.",
        "Draft a note about turning JSA and incident notes into clean packets. Review before sending.",
    ),
    "Water and Wastewater": (
        "Confirm they prepare monthly operating reports or DMRs for clients.",
        "Draft a note about a DMR draft helper a person still signs off on. Review before sending.",
    ),
    "Hazmat Trucking": (
        "Pull their FMCSA snapshot and note DQ file or hazmat training burden.",
        "Draft a note about keeping DQ and training records audit-ready. Review before sending.",
    ),
    "Waste Haulers": (
        "Confirm they haul regulated waste and note manifest paperwork.",
        "Draft a note about cleaner manifest and route compliance packets. Review before sending.",
    ),
    "Ag Chemical Dealers": (
        "Check whether they handle applicator records or chemical transport docs.",
        "Draft a note about seasonal applicator and transport paperwork. Review before sending.",
    ),
}


def load_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key and key != "paste-your-key-here":
        return key
    for env_file in (
        ROOT / "typesafe.env",
        Path("/workspace/break-room/typesafe.env"),
        Path("/workspace/calibrated/typesafe.env"),
        Path("/workspace/two14-jev-eval/typesafe.env"),
    ):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "TYPESAFE_API_KEY":
                val = v.strip().strip('"').strip("'")
                if val and val != "paste-your-key-here":
                    return val
    secrets = Path("/home/box/agent-data/box-secrets.json")
    if secrets.exists():
        data = json.loads(secrets.read_text(encoding="utf-8"))
        key = (data.get("card") or {}).get("TYPESAFE_API_KEY") or ""
        if key:
            return str(key).strip()
    raise SystemExit("TYPESAFE_API_KEY not found (never print keys)")


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def call_jev(state: str, questions: dict) -> dict:
    key = load_key()
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        API,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; LeadRadar/0.1)",
            "Origin": "https://console.typesafe.ai",
            "Referer": "https://console.typesafe.ai/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def score_to_100(raw) -> int:
    try:
        s = float(raw)
    except (TypeError, ValueError):
        return 50
    # Jev score criteria are 0..4
    return max(0, min(100, int(round((s / 4.0) * 100))))


def load_base_leads() -> list[dict]:
    csv_path = Path("/workspace/shared/marzipan-scored-v2.csv")
    centroids = json.loads((ROOT / "city_centroids.json").read_text(encoding="utf-8"))
    leads = []
    for row in csv.DictReader(csv_path.open(encoding="utf-8")):
        industry = INDUSTRY_MAP.get(row["scout_tab"], row["scout_tab"])
        city = (row.get("city") or "").strip()
        state = (row.get("state") or "").strip()
        key = f"{city}|{state}"
        latlon = centroids.get(key)
        if not latlon and city:
            # fallback: state capital-ish / stillwater offset
            latlon = STILLWATER
        dist = haversine_miles(STILLWATER, tuple(latlon)) if latlon else None
        desc = row.get("description") or ""
        # Strip internal tracker notes from public description
        public_bits = []
        for part in desc.split(" | "):
            pl = part.lower()
            if "kit tracker" in pl or part.startswith("Notes:"):
                continue
            public_bits.append(part)
        public_desc = " | ".join(public_bits)[:280]
        next_action, draft = NEXT_TEMPLATES.get(
            industry,
            (
                "Do a light research pass on their public site or listing.",
                "Draft a short intro note. Review before sending.",
            ),
        )
        leads.append(
            {
                "id": row["company_id"],
                "name": row["company"],
                "industry": industry,
                "city": city,
                "state": state,
                "website": (row.get("website") or "").strip() or None,
                "source_link": (row.get("source_link") or "").strip() or None,
                "description": public_desc,
                "lat": latlon[0] if latlon else None,
                "lon": latlon[1] if latlon else None,
                "miles_from_stillwater": round(dist, 1) if dist is not None else None,
                "prior_fit": int(float(row["fit"])) if row.get("fit") else None,
                "score": None,
                "reason": None,
                "reason_key": None,
                "confidence": None,
                "next_action": next_action,
                "draft_note": draft,
                "stage": "New",
            }
        )
    return leads


def batch_score(leads: list[dict]) -> dict:
    usage_acc = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0, "estimated": True}
    for i in range(0, len(leads), BATCH):
        batch = leads[i : i + BATCH]
        state_lines = [
            "Score each lead for Marzipan Solutions fit.",
            "Marzipan helps small regulated businesses near Stillwater OK turn messy paperwork into clean, human-checked reports.",
            "Prefer: small, local, regulated, paperwork-heavy, likely no in-house IT or compliance staff.",
            "Avoid: national chains, government agencies, firms that already look well-tooled.",
        ]
        questions = {}
        for lead in batch:
            cid = lead["id"]
            bits = [
                f"[{cid}] {lead['name']}",
                f"{lead['city']}, {lead['state']}",
                f"industry={lead['industry']}",
            ]
            if lead.get("description"):
                bits.append(lead["description"][:200])
            if lead.get("prior_fit") is not None:
                bits.append(f"prior_fit_hint={lead['prior_fit']}")
            state_lines.append(" | ".join(bits))
            questions[f"fit_{cid}"] = {
                "type": "score",
                "instructions": f"Score fit of [{cid}] {lead['name']} for Marzipan. Higher is better.",
                "criteria": FIT_CRITERIA,
            }
            questions[f"reason_{cid}"] = {
                "type": "choice",
                "instructions": f"Pick the best one-line reason for [{cid}] {lead['name']}.",
                "criteria": REASON_LABELS,
            }
        try:
            raw = call_jev("\n".join(state_lines), questions)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            print(f"Jev HTTP {e.code} on batch {i}: {detail}", flush=True)
            # fallback to prior fit
            for lead in batch:
                lead["score"] = lead.get("prior_fit") or 50
                lead["reason"] = REASON_LABELS["thin_signal"]
                lead["reason_key"] = "thin_signal"
                lead["confidence"] = 0.0
            continue
        except Exception as e:
            print(f"Jev error on batch {i}: {e}", flush=True)
            for lead in batch:
                lead["score"] = lead.get("prior_fit") or 50
                lead["reason"] = REASON_LABELS["thin_signal"]
                lead["reason_key"] = "thin_signal"
                lead["confidence"] = 0.0
            continue

        usage = raw.get("usage") or {}
        usage_acc["calls"] += 1
        usage_acc["input_tokens"] += int(usage.get("input_tokens") or 0)
        usage_acc["output_tokens"] += int(usage.get("output_tokens") or 0)
        if usage.get("cost_usd") is not None:
            usage_acc["cost_usd"] += float(usage["cost_usd"])
            usage_acc["estimated"] = False
        else:
            usage_acc["cost_usd"] += (
                int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
            ) * EST_USD_PER_TOKEN

        answers = raw.get("answers") or {}
        for lead in batch:
            cid = lead["id"]
            fit = answers.get(f"fit_{cid}") or {}
            reason = answers.get(f"reason_{cid}") or {}
            lead["score"] = score_to_100(fit.get("score"))
            rkey = reason.get("choice") or "thin_signal"
            lead["reason_key"] = rkey
            lead["reason"] = REASON_LABELS.get(rkey, REASON_LABELS["thin_signal"])
            try:
                lead["confidence"] = round(float(fit.get("confidence") or 0), 2)
            except (TypeError, ValueError):
                lead["confidence"] = 0.0
        print(
            f"scored {i + len(batch)}/{len(leads)} "
            f"(tokens in={usage.get('input_tokens')} out={usage.get('output_tokens')})",
            flush=True,
        )
        time.sleep(0.15)
    return usage_acc


# ---------------------------------------------------------------------------
# --local: all small businesses in Stillwater, Cushing, Perry, Morrison.
# Input comes from collect_local.py (local_candidates.json). Scores are
# merged into the existing leads.json; the regulated leads stay untouched.
# ---------------------------------------------------------------------------

LOCAL_TOWNS = ["Stillwater", "Cushing", "Perry", "Morrison"]

LOCAL_REASONS = {
    "field_reports": "Field crew whose job notes, photos and logs become reports by hand",
    "compliance_records": "Regulated work with recurring compliance records to keep straight",
    "client_followups": "Steady client intake, reminders and follow-up emails a small staff handles",
    "document_office": "Office that runs on documents: client files, forms, and paperwork",
    "sop_lookup": "Staff dig through manuals, price books or old job files for answers",
    "recurring_reports": "Someone likely builds the same report or schedule by hand every week",
    "light_admin": "Small shop with light admin; low paperwork pain",
    "corporate_systems": "Chain, franchise, or large org that likely runs corporate systems",
    "thin_signal": "Thin public signal; worth a light research pass",
}

LOCAL_CRITERIA = [
    "Poor fit: chain, franchise, nonprofit, or no repeating office work to automate",
    "Weak fit: tiny walk-in shop with light admin, or already well-tooled",
    "Moderate fit: some repeating admin or follow-ups, but a modest payoff",
    "Strong fit: small local team with a clear repeating paperwork, report, or follow-up job",
    "Excellent fit: small local team buried in field reports, compliance records, or client paperwork, no IT staff",
]

LOCAL_NEXT = {
    "Medical & Dental": "Ask who handles intake forms, recall reminders, and insurance paperwork, and how long it takes them each week.",
    "Veterinary & Animal": "Ask how vaccine reminders and visit follow-ups go out today.",
    "Legal": "Ask which documents they rebuild from scratch for every client.",
    "Accounting & Finance": "Ask how client documents come in at tax time and who chases the missing ones.",
    "Insurance": "Ask how renewals, quote follow-ups, and certificate requests are tracked.",
    "Real Estate & Property": "Ask how work orders, lease paperwork, and tenant messages are handled.",
    "Trades & Contractors": "Ask how a job goes from field notes and photos to an invoice or closeout packet.",
    "Energy & Industrial": "Ask which field tickets, safety forms, or compliance logs get retyped in the office.",
    "Auto & Equipment": "Ask how estimates, service reminders, and parts orders are tracked.",
    "Lodging & Events": "Ask how bookings, event contracts, and guest follow-ups are handled.",
    "Professional Services": "Ask which weekly report or client update they build by hand.",
    "Childcare & Education": "Ask how enrollment forms, attendance, and parent messages are handled.",
    "Salon & Personal Care": "Ask how no-shows, rebooking reminders, and product orders are handled.",
    "Fitness & Recreation": "Ask how memberships, waivers, and lapsed-member follow-ups are handled.",
    "Food & Drink": "Ask how catering orders, supplier orders, and the weekly schedule get done.",
    "Retail": "Ask how inventory reorders and special orders are tracked.",
    "Agriculture": "Ask which seasonal records or customer orders are kept on paper.",
}


def load_local_leads() -> list[dict]:
    src = json.loads((ROOT / "local_candidates.json").read_text(encoding="utf-8"))
    leads = []
    for r in src:
        leads.append(
            {
                "id": r["id"],
                "name": r["name"],
                "industry": r["industry"],
                "city": r["town"],
                "state": "OK",
                "website": r.get("website"),
                "source_link": r.get("source_link"),
                "source": r.get("source"),
                "address": r.get("address"),
                "description": "; ".join(
                    x for x in (r["industry"], (r.get("osm_type") or "").replace("_", " "), r.get("address")) if x
                ),
                "lat": r["lat"],
                "lon": r["lon"],
                "miles_from_stillwater": r["miles_from_stillwater"],
                "score": None,
                "reason": None,
                "reason_key": None,
                "confidence": None,
                "next_action": LOCAL_NEXT.get(r["industry"], "Do a light research pass on their public listing."),
                "draft_note": "Draft a short intro note. Review before sending.",
                "stage": "New",
                "segment": "Local small business",
            }
        )
    return leads


def score_local(leads: list[dict]) -> dict:
    usage_acc = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0, "estimated": True, "failed_batches": 0}
    context = [
        "Score each local business for fit with Marzipan Solutions (Stillwater, OK, one-person shop run by Kit Applegate).",
        "Marzipan builds small automation tools for businesses without a developer, each around one job the team already repeats:",
        "1) AI search that answers from the business's own SOPs, manuals and old job files;",
        "2) reports that build and send themselves on a schedule;",
        "3) scheduled agents that sort requests and draft follow-ups for a person to approve;",
        "4) field-to-report paperwork: job notes, photos and voice memos into daily logs and closeout packets.",
        "Prefer: locally owned, small staff, a repeating paperwork, report, intake or follow-up job, no IT staff.",
        "Avoid: chains, franchises, hospitals, nonprofits, government, and tiny walk-in shops with little office work.",
        "Judge from the name and type only; do not invent facts. Leads:",
    ]
    for i in range(0, len(leads), BATCH):
        batch = leads[i : i + BATCH]
        state_lines = list(context)
        questions = {}
        for lead in batch:
            cid = lead["id"]
            state_lines.append(f"[{cid}] {lead['name']} | {lead['city']}, OK | {lead['description']}")
            questions[f"fit_{cid}"] = {
                "type": "score",
                "instructions": f"Score fit of [{cid}] {lead['name']} for Marzipan. Higher is better.",
                "criteria": LOCAL_CRITERIA,
            }
            questions[f"reason_{cid}"] = {
                "type": "choice",
                "instructions": f"Pick the best one-line reason for [{cid}] {lead['name']}.",
                "criteria": LOCAL_REASONS,
            }
        raw = None
        for attempt in range(3):
            try:
                raw = call_jev("\n".join(state_lines), questions)
                break
            except urllib.error.HTTPError as e:
                print(f"Jev HTTP {e.code} on batch {i} (try {attempt + 1}): {e.read().decode(errors='replace')[:200]}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"Jev error on batch {i} (try {attempt + 1}): {e}", flush=True)
            time.sleep(3 * (attempt + 1))
        if raw is None:
            usage_acc["failed_batches"] += 1
            for lead in batch:  # left unscored, flagged so the UI can show it
                lead.update(score=None, reason=LOCAL_REASONS["thin_signal"], reason_key="unscored", confidence=0.0)
            continue
        usage = raw.get("usage") or {}
        usage_acc["calls"] += 1
        usage_acc["input_tokens"] += int(usage.get("input_tokens") or 0)
        usage_acc["output_tokens"] += int(usage.get("output_tokens") or 0)
        if usage.get("cost_usd") is not None:
            usage_acc["cost_usd"] += float(usage["cost_usd"])
            usage_acc["estimated"] = False
        else:
            usage_acc["cost_usd"] += (int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)) * EST_USD_PER_TOKEN
        answers = raw.get("answers") or {}
        for lead in batch:
            cid = lead["id"]
            fit = answers.get(f"fit_{cid}") or {}
            reason = answers.get(f"reason_{cid}") or {}
            lead["score"] = score_to_100(fit.get("score")) if fit.get("score") is not None else None
            rkey = reason.get("choice") if reason.get("choice") in LOCAL_REASONS else "thin_signal"
            lead["reason_key"] = rkey
            lead["reason"] = LOCAL_REASONS[rkey]
            try:
                lead["confidence"] = round(float(fit.get("confidence") or 0), 2)
            except (TypeError, ValueError):
                lead["confidence"] = 0.0
        print(f"scored {i + len(batch)}/{len(leads)}", flush=True)
        time.sleep(0.15)
    return usage_acc


def main_local(limit: int | None) -> None:
    leads = load_local_leads()
    if limit:
        leads = leads[:limit]
    print(f"Loaded {len(leads)} local leads", flush=True)
    usage = score_local(leads)
    if limit:
        for l in leads:
            print(f"{l['score']!s:>4} {l['confidence']:.2f} {l['reason_key']:<18} {l['name']} ({l['industry']}, {l['city']})")
        print(json.dumps(usage))
        print("Dry run (--limit): leads.json not changed.")
        return
    data = json.loads((ROOT / "leads.json").read_text(encoding="utf-8"))
    kept = [l for l in data["leads"] if l.get("segment") != "Local small business"]
    for l in kept:
        l.setdefault("segment", "Regulated prospect")
    merged = kept + leads
    merged.sort(key=lambda x: (-(x.get("score") or 0), x.get("name") or ""))
    data["leads"] = merged
    data["industries"] = sorted({l["industry"] for l in merged})
    data["segments"] = ["Regulated prospect", "Local small business"]
    data["local_scoring"] = {
        "model": "jev-latest",
        "generated_at": time.strftime("%Y-%m-%d"),
        "towns": LOCAL_TOWNS,
        **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in usage.items()},
    }
    data["disclaimer"] = (
        "Proof of concept for Marzipan Solutions. Public business information only "
        "(Scout regulated list; OpenStreetMap contributors, ODbL; Cushing Chamber and Downtown Perry Main Street directories). "
        "Not legal advice. Nothing sends on its own."
    )
    (ROOT / "leads.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    scores = [l["score"] for l in leads if l.get("score") is not None]
    print(json.dumps({
        "local_leads": len(leads), "scored": len(scores), "total_leads": len(merged),
        "score_avg": round(sum(scores) / len(scores), 1) if scores else None,
        "strong_75plus": sum(1 for s in scores if s >= 75), "jev": usage,
    }, indent=2))


def main() -> None:
    if "--local" in sys.argv:
        lim = None
        if "--limit" in sys.argv:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        main_local(lim)
        return
    leads = load_base_leads()
    print(f"Loaded {len(leads)} leads", flush=True)
    usage = batch_score(leads)
    # Drop prior_fit from public output (internal hint only)
    public = []
    for lead in leads:
        item = {k: v for k, v in lead.items() if k != "prior_fit"}
        public.append(item)
    public.sort(key=lambda x: (-(x.get("score") or 0), x.get("name") or ""))
    out = {
        "generated_at": "2026-11-09",
        "center": {"city": "Stillwater", "state": "OK", "lat": STILLWATER[0], "lon": STILLWATER[1]},
        "scoring": {
            "model": "jev-latest",
            "calls": usage["calls"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd": round(usage["cost_usd"], 6),
            "cost_estimated": usage["estimated"],
        },
        "industries": sorted(INDUSTRY_MAP.values()),
        "stages": ["New", "Researched", "Warm intro", "Talked", "Proposal"],
        "leads": public,
        "disclaimer": "Proof of concept for Marzipan Solutions. Public business information only. Not legal advice. Nothing sends on its own.",
    }
    (ROOT / "leads.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (ROOT / "score_report.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
    scores = [l["score"] for l in public if l.get("score") is not None]
    print(
        json.dumps(
            {
                "leads": len(public),
                "score_min": min(scores) if scores else None,
                "score_max": max(scores) if scores else None,
                "score_avg": round(sum(scores) / len(scores), 1) if scores else None,
                "jev": usage,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
