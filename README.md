# Damage Assessment

Photograph accident damage, get a structured assessment and a costed repair
estimate.

## Setup

```bash
pip install -r requirements.txt
```

Paste your Groq key into `.env` after `GROQ_API_KEY=` — no quotes, no spaces
around the `=`. Then:

```bash
python server.py
```

Open <http://127.0.0.1:5056>. The server binds `0.0.0.0`, so you can also reach
it from a phone on the same wifi at `http://<your-machine-ip>:5056` — which is
how you'd actually use it, since the capture button opens the rear camera.

## How it works

**The model never produces a price.** It is asked for perception only: which
part, what kind of damage, how severe, and which repair operation applies. Those
come back as constrained enums.

**`rates.json` turns findings into money.** Labour hours per operation and
severity, a paint material rate, and a low/high parts band per component. Given
the same findings it returns the same numbers every time, and every figure
traces to a line you can edit and argue with.

That split is the whole design. A model that outputs "RM 2,400" is unauditable —
nobody can tell which part of it is wrong. Here you can point at the line.

To retune for your market, edit `rates.json` alone. Nothing else needs to change.

## What it refuses to do

- **Invent a vehicle.** Photograph something that isn't a car and it reports
  `is_vehicle: false` with no findings. Verified against a test image.
- **Invent damage.** No visible damage means an empty findings list, not a
  helpfully padded one.
- **Pretend one photo is enough.** `photo_quality` downgrades on blur, distance
  or bad light, and says what a better photo would need to show. Damage that
  likely continues out of frame goes in `hidden_damage_risk` rather than
  becoming a priced line.
- **Bury safety.** Anything suggesting the vehicle is unsafe to drive — fluid
  loss, a wheel at the wrong angle, shattered glass, a dragging part — surfaces
  in a red banner above everything else.

Every finding carries its own confidence score, shown in the report.

## Files

| File | |
|---|---|
| `assess.py` | the assessor prompt, part/action/damage enums, response schema |
| `rates.json` | every number that becomes money |
| `pricing.py` | findings → itemised estimate. No model calls |
| `llm.py` | Groq vision call |
| `db.py` | assessment history, photo kept with the report |
| `server.py` | JSON API + static |
| `static/index.html` | capture, report, history |

## Model

`qwen/qwen3.6-27b` — currently the only vision-capable model on Groq. Set
`DAMAGESCAN_MODEL` in `.env` to change it.

Photos are downscaled to 800px in the browser before upload. A raw phone photo
costs several thousand tokens once the model tiles it, and the free tier allows
8000 per minute in total. If you hit rate limits, lower `MAX_EDGE` in
`static/index.html`.

## Deploying to Render

`render.yaml` is a blueprint — point Render at this repo and it reads the build
command, start command, health check and environment.

Two variables must be set in the Render dashboard, not in the repo:

| Variable | |
|---|---|
| `GROQ_API_KEY` | your key |
| `DAMAGESCAN_ACCESS_CODE` | a shared code callers must enter first |

**Set the access code.** Without it the deployed URL is an open endpoint
spending your Groq quota, and the free tier is exhausted by a handful of
requests. A public URL gets found.

Two rate limits back it up — `DAMAGESCAN_RATE_PER_IP` (12/hour) stops one
person hammering it, and `DAMAGESCAN_RATE_GLOBAL` (60/hour) is what actually
protects the quota, since an attacker with a pool of addresses walks straight
past a per-IP rule. Neither a rejected code nor a malformed upload consumes an
allowance.

Counters are held in memory, so the service runs a single worker. That is the
right shape regardless: Groq's per-minute budget means concurrent requests would
only fail behind each other.

### Known limits of the free plan

- **No persistent disk**, so `assessments.db` is wiped on every restart and
  history does not survive. Set `DAMAGESCAN_DB` to a path on a mounted disk on
  a paid plan to keep it.
- **The service sleeps when idle.** The first request after a sleep waits for a
  cold start on top of the 10–30 seconds a vision call already takes.

## Not built yet

- **Multiple photos per assessment.** One angle is one angle; real assessments
  want four. The schema and pricing already handle a merged findings list — the
  missing piece is deduplicating the same dent seen twice.
- **Vehicle identification.** Make and model would let parts prices come from a
  real catalogue instead of a generic band.
- **PDF export** for insurers.
- **Rate profiles** — one `rates.json` per region or workshop.
