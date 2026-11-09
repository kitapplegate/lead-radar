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
4. **Next step** - suggested action and a draft note marked **Review before sending** (nothing sends)

## Data

Public business information only, from Scout's Regulated Prospects list (about 169 firms, Oct 2026). No private personal contact info. City coordinates use an offline centroid lookup for OK, KS, MO, AR, and TX. Not legal advice.

## Scoring

Leads are pre-scored offline with TypeSafe **Jev** (`build_leads.py`). The demo page does not call the API. Scores and reasons are cached in `leads.json`.

```bash
# Needs TYPESAFE_API_KEY in the environment or a local typesafe.env (gitignored)
python3 build_leads.py
```

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

Built for a lunch demo with Mark Austin. Marzipan Solutions.
