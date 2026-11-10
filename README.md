# Lead Radar

Proof-of-concept lead finder and mini CRM for **Marzipan Solutions** (Stillwater, OK).

Marzipan finds small regulated businesses near Stillwater and helps work them as leads: labs, spill response, oilfield services, water and wastewater, hazmat trucking, waste haulers, and ag chemical dealers.

## Live demo

Open the GitHub Pages site after it is enabled:

**https://kitapplegate.github.io/lead-radar/**

## What it shows

1. **Find** - filter by industry and radius from Stillwater, map pins, list sorted by Jev fit score
2. **Score** - each lead has a 0 to 100 Jev score and a one-line reason
3. **Track** - pipeline stages: New, Researched, Warm intro, Talked, Proposal (saved in localStorage)
4. **Next step** - suggested action plus **Draft outreach** (industry templates filled with the lead name, city, and Jev reason). Edit, copy, or open in email. Edits stay in localStorage. Nothing sends on its own.

## Data

Public business information only: Scout's Regulated Prospects list (167 firms, Oct 2026), OpenStreetMap (© OpenStreetMap contributors, ODbL), the Cushing Chamber and Downtown Perry Main Street directories, and us-business.info listings for Pawnee. No private personal contact info. City coordinates use an offline centroid lookup for OK, KS, MO, AR, and TX. Not legal advice.

## Scoring

Leads are pre-scored offline with TypeSafe **Jev** (`build_leads.py`). The demo page does not call the API. Scores and reasons are cached in `leads.json`.

```bash
# Needs TYPESAFE_API_KEY in the environment or a local typesafe.env (gitignored)
python3 build_leads.py
```

## Local small businesses (Stillwater, Cushing, Perry, Morrison, Pawnee)

A second segment covers every small business in those five towns, not just regulated firms. The **Leads** filter switches between segments.

1. `python3 collect_local.py` pulls named businesses from OpenStreetMap (cached in `local_osm_raw.json`; `--refresh` refetches), drops non-businesses and chains, buckets them into categories, and merges the hand-curated directory lists in `sources/*.tsv` (Cushing Chamber, Downtown Perry Main Street, and Pawnee listings from the us-business.info aggregator, which may include stale entries). Street addresses are geocoded with the free US Census geocoder (`sources/geocode_cache.json`). Output: `local_candidates.json`.
2. `python3 build_leads.py --local` scores them with Jev against Marzipan's four services (SOP search, reports that run, scheduled agents, field-to-report paperwork) and merges them into `leads.json`. The regulated leads are left as they are. Scoring is incremental: leads that already have a score keep it, so adding a town only scores the new businesses (`--rescore` redoes everything). `--limit 20` is a dry run that prints scores without writing anything. New towns go in `TOWNS` (and `ZIPS`) in `collect_local.py`.

Captive insurance agents (State Farm, Allstate, etc.) are kept as leads, since each is a locally owned office. The Stillwater Chamber has no public directory right now, so Stillwater coverage comes from OSM, which is light on offices.

## Local preview

```bash
python3 -m http.server 8765
# open http://127.0.0.1:8765
```

## Files

| File | Purpose |
|------|---------|
| `index.html` | Mobile-first app (Leaflet map via CDN) |
| `leads.json` | Pre-scored public leads |
| `build_leads.py` | Batch Jev scoring |
| `city_centroids.json` | Offline city lat/lon lookup |
| `collect_local.py` | Collects local small businesses (OSM + directories) |
| `local_candidates.json` | Unscored local businesses, input to `build_leads.py --local` |
| `sources/` | Hand-curated directory lists and geocode cache |

Built for a lunch demo with Mark Austin. Marzipan Solutions.
