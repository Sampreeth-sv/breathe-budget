# Breathe Budget

A smog-smart planning assistant for families and neighbourhoods. Enter a city and a few details about your household and day, and it returns:

- today's **live PM2.5 / AQI** for your city and what it means for *your* household,
- a **ranked list of low-emission and low-cost actions**, each with the **estimated drop in the PM2.5 you breathe** and, where relevant, the CO₂e you avoid,
- the **cleanest hour** of the day, **guidance per family member** (children, older adults, asthma/COPD/heart conditions, adults), and a **neighbourhood plan**,
- a plain-language explanation, written by Gemini when a key is configured and by rules otherwise.

Built for the Google PromptWars problem statement *"Urban Air Quality Assessment"*.

## How it answers the problem statement

| Requirement | Where it lives |
|---|---|
| Tailored to **location** | City geocoded and live PM2.5 forecast fetched from Open-Meteo (CAMS); optional own-monitor override |
| Tailored to **lifestyle** | Commute mode and length, cooking fuel, heating, outdoor exercise, existing purifier |
| **Families and communities** | Household composition drives risk escalation and per-member advice; a neighbourhood size turns per-home savings into community CO₂e and a pledge list |
| **Low-emission daily routines** | Transit/carpool swaps, exercise timing, cleanest-hour ventilation |
| **Indoor air quality hacks** | HEPA or DIY Corsi-Rosenthal box, sealing gaps, venting the kitchen, indoor workouts |
| **Sustainable alternatives** | Clean cooking and heating swaps, transit, carpooling, with CO₂e shown |
| **Clearly explaining the direct impact** | Every action carries a computed "cuts your exposure by X%" figure, plus a before/after bar for the whole plan |

## Design: the numbers are computed, not generated

The impact figures come from a small deterministic model (`app/services/exposure.py`), not from the LLM:

```
daily dose (µg) = Σ  concentration × breathing rate × hours   over home, commute and exercise
```

Each action is a counterfactual: the model is re-run with one habit changed and the difference is reported (`app/services/rules.py`). That makes the impact figures reproducible and unit-tested. Gemini only receives the finished numbers and phrases them; if it is unavailable, slow or returns something unusable, the app falls back to a rule-based summary rather than failing.

All constants in the model (infiltration, mask efficiency, source strengths, breathing rates) are **stated assumptions** chosen from typical literature ranges. The results are for comparing choices against each other, **not** clinical measurements or medical advice, and the app says so.

```
app/
  main.py              app factory, security headers, body-size cap, rate limiting
  config.py            env-based settings, validated and clamped
  schemas.py           Pydantic request/response models (strict, bounded, closed enums)
  ratelimit.py         in-memory sliding-window limiter
  routers/advice.py    thin HTTP handlers
  services/
    exposure.py        pure functions: AQI conversion + dose model
    rules.py           interventions, ranking, household guidance
    advisor.py         orchestration of one request
    aqi_client.py      async Open-Meteo client with TTL cache and timeouts
    llm.py             Gemini explainer with validation and fallback
    cache.py           TTL cache
  static/              semantic HTML, CSS, vanilla JS (no build step, no inline code)
tests/                 136 tests
```

## Security

- **Input validation**: every field bounded; enums are closed sets; unknown fields rejected; `city` restricted to letters and `. , ' -`, so injection payloads and markup never get past validation. Validation errors never echo submitted text back.
- **Prompt injection**: the only free text (`city`) never reaches the LLM. The model receives computed numbers and fixed labels only, and its output is stripped of markup and length-capped.
- **XSS**: the frontend uses `textContent` only (a test asserts `innerHTML` is never used), and a strict CSP (`default-src 'self'`, no inline script or style) is sent on every response.
- **Secrets**: the Gemini key is read from the environment only, never logged or returned; `.env` is git-ignored and `.env.example` documents the variables.
- **Abuse control**: per-IP rate limit (429 with `Retry-After`), 8 KB request cap (413), upstream timeouts, bounded caches, API docs endpoints disabled, `Cache-Control: no-store` on API responses.
- **Privacy**: no accounts, no database, nothing the user enters is stored.
- Container runs as a non-root user.

## Efficiency

Air data is cached per location (15 min) and geocoding per city (24 h), so repeated requests cost no upstream calls. The rule engine is pure CPU and answers in milliseconds; the optional Gemini call has a hard timeout and is the only thing that can add latency, and it degrades to the rule-based text if it does.

## Accessibility

Semantic landmarks and heading order, a skip link, every control has a programmatic label, visible focus rings, an error summary with links to the offending fields, focus moved to the results and announced through a live region, 44 px touch targets, light and dark themes, reduced-motion support, and a layout that works at 360 px without horizontal scrolling. Risk and cost are always conveyed in **words and icons, never colour alone**.

Checked with axe-core 4.10 in Chromium: **0 violations** in light and dark themes across the empty form, the error state and the results state. Keyboard-only flow (skip link, Enter to submit) verified.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest --cov
```

136 tests, ~99.7% line coverage. They cover the AQI conversion at every EPA breakpoint and bounds, the dose model's monotonicity and edge cases, ranking and recommendations for clean/smoggy/biomass/commuting households, the Open-Meteo client against mocked responses (including malformed data, timeouts and caching), Gemini success, timeout and bad-output paths, the full API (success, 404, 503 fallback, 22 invalid-input cases including injection strings, 413, 429, security headers) and the frontend's accessibility and safety invariants. CI runs the same suite on every push (`.github/workflows/ci.yml`).

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: add GEMINI_API_KEY
export $(grep -v '^#' .env | xargs)   # or set the variable your own way
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

The app works without a Gemini key. The explanation is then written from rules and labelled as such.

## Deploy

**Google Cloud Run** (recommended):

```bash
gcloud run deploy breathe-budget --source . --region asia-south1 \
  --allow-unauthenticated --set-env-vars GEMINI_API_KEY=YOUR_KEY
```

(Or store the key in Secret Manager and use `--set-secrets GEMINI_API_KEY=name:latest`.)

**Render**: New → Blueprint → select this repo (`render.yaml` is included), then set `GEMINI_API_KEY` in the dashboard.

## Limitations

- PM2.5 is a **modelled forecast** (CAMS), not a ground-station reading; local conditions can differ. Users can enter their own monitor's reading, which overrides it.
- The exposure model is intentionally simple and its constants are assumptions.
- The in-memory rate limiter and caches are per instance; for many instances use a shared store.

## Data and standards

Air data: [Open-Meteo](https://open-meteo.com/) (Copernicus CAMS). AQI: US EPA PM2.5 breakpoints (2024). Reference level: WHO 2021 guideline (15 µg/m³, 24-hour).
