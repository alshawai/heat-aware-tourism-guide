# Heat-Aware Tourism Guide — Design Doc

Most map apps answer "how do I get there?" by optimizing a single number — distance, or time. This system answers two questions a tourist actually has — _when_ to visit a landmark and _how_ to walk to it — under a constraint those apps never face: the temperature data that makes the answers good is metered and billed per job, and the analysis that makes them precise takes seconds to minutes. So the design is organized around one rule: **do the expensive thing only when a free thing has already proven it's necessary.** Routing is fetched exactly once per request. Shade is computed, never photographed. A city district's worth of hotels is ranked with a single API call.

This document is the source of truth for building that system. Every decision below is recorded with the reason behind it, because most of them look arbitrary until you see the constraint that forced them — and an implementer who can't see the constraint will "fix" the design straight back into the naive, expensive version it was built to avoid. Where a decision still rests on something unverified against the live API, it is marked as such rather than assumed.

## FortyGuard: the metered resource

FortyGuard is a heat-data platform: give it a place and a time, and it returns real outdoor thermal conditions — temperature and thermal-comfort values tied to specific coordinates and specific hours. It is the only reason this system can say anything true about heat, and it is the resource the entire design is built to spend carefully.

Two properties of the platform drive every cost decision that follows. First, it is **job-based and metered**: you submit a request, poll until the job reports `Completed`, then read the result — and each job draws down a quota, which during the hackathon is a finite trial balance. Second, its **latency is uneven**: most jobs return in seconds, but the heaviest — a full PDF report — takes minutes, far too long to sit on the path of a live interaction. Treat FortyGuard as a free, instant lookup and you get the worst of both: credits exhausted before the demo, and the screen frozen on a job that won't return in time.

The platform exposes several endpoints — a heatmap generator, a per-point environmental query, two image-segmentation services, and a report builder — split across a Basic and a Premium plan. Rather than catalog them here, this doc introduces each one at the moment a feature first needs it, so every endpoint arrives attached to the job it does.

## What the system does

The system supports a single trip, framed as three linked decisions a heat-exposed tourist has to make:

- **When to visit a landmark.** For a chosen landmark, an hour-by-hour read of thermal comfort across the day, reduced to a short recommendation — the best two or three hours to go, with the reason attached.
- **Where to stay.** A ranking of the hotels in a district by how hot their _surroundings_ get — a **Neighbourhood Heat Score** that predicts whether stepping outside in the evening is pleasant and how walkable the area is, not whether the room is comfortable.
- **How to get there.** From a starting point to the landmark at the chosen hour, a walking route picked for shade and heat exposure rather than distance alone — with the shortest and the shadiest routes shown side by side when they differ.

These decisions are deliberately coupled. The visit hour chosen in the first is the hour the route is evaluated for in the third; the heat data pulled for the landmark feeds both. The product's value is in answering the three together, under one budget, instead of as three unrelated lookups — which is exactly what makes spending discipline the central design problem rather than an afterthought.

## Design invariants

Four rules run through every feature below. They are stated here once, as invariants, because each is a place where the obvious local "improvement" is the expensive mistake — an implementer optimizing one piece in isolation will reintroduce exactly the cost the design was built to remove. When a later section looks like it bends one of these, that is a signal to re-read the section, not to refactor it.

**1. Fetch routing exactly once per request.** All route work — deciding short versus long, scoring shade, ranking the options, drawing the map — reuses a single set of candidate routes, pulled from the routing provider at one point in the flow. No branch, mild or hot, may query it again. A second routing call for the same request is a bug, not an optimization: the candidate routes do not change between the heat check and the shade check, so re-fetching spends latency to get the same polylines back.

**2. A free check gates every paid one.** No paid job runs until a free computation has shown the cheap answer won't do. If the heat along a route turns out mild, the system shows the shortest path and stops — it never scores shade, never spends a credit it didn't need. The expensive work exists, but it sits downstream of a gate, and the gate is free. Pre-fetching "to be safe" defeats the entire cost model.

**3. Sample heat where it is representative, and aggregate toward the worst case.** A reading is only worth acting on if it reflects what the user will actually feel. A single point at the landmark can stand in for a short walk; a longer walk is judged across the whole corridor it passes through. And where several readings cover one route, the decision uses the **maximum**, never the mean — a short brutal stretch of full sun ruins a walk whose average still reads "fine." If you find yourself averaging temperature over a path, stop.

**4. Prefer an exact free computation to a paid, ambiguous fetch.** When a quantity can be derived exactly from open data and deterministic math, the design does not pay an API to approximate it. The flagship case, spelled out later, is shade: computed from sun geometry rather than detected from imagery — free, instant, and _more_ correct than the paid alternative, not less. A paid endpoint is reached for only when the thing it measures genuinely cannot be computed.

## Decision 1: When to visit

The first decision needs an hour-by-hour picture of thermal comfort at a single point — the landmark — across one day. Two FortyGuard endpoints produce it. **`create-heatmap`** is the platform's core generator: given an area or a point and a time, it returns temperature as a grid of tiles, and asked for the analytic type `tcm` (a thermal-comfort or "feels-like" measure, not raw air temperature) it reports what the heat actually does to a body standing there. **`environmental-parameters`** queries a single point for the breakdown behind that number — heat index, humidity, wet-bulb temperature. Run either across the hours of the day and the result is a curve: how comfort at the landmark climbs and falls from morning to night.

A curve of raw numbers is not yet a recommendation. The system bins each hour into a **comfort band** — comfortable, moderate, hot, dangerous — aligned to the published NOAA heat-index scale rather than to an invented one. NOAA, the US weather service, defines a fixed set of "feels-like" ranges, each tied to a risk level from caution up through danger, with published boundary temperatures. Binning to those bands means every category the app displays is defensible against a public standard instead of a threshold the team chose. The best two or three hours are then just the coolest bands of the day, surfaced with the reason attached: not "visit at 6 p.m." but "visit at 6 p.m. — two bands cooler than noon."

Both calls are cheap and return in seconds, and unlike the route engine described later, they have no free substitute — real heat data is the one thing the system cannot compute for itself. So the discipline here is not gating but caching: a landmark's curve does not change over the course of a demo, so it is fetched once per landmark per day and reused for every question that follows about that landmark.

The same `create-heatmap` generator, asked different questions, turns that curve into something a person remembers. Two more of its analytic modes do the framing. **`exceedance`** counts how many hours cross a heat threshold — "nine hours above 35 °C today." **`persistence`** measures the longest unbroken stretch above it — "six of them back to back, with no relief in between." A running total and an unbroken run say different things: the first is total exposure, the second is whether the heat ever lets up. And because `create-heatmap` accepts a start time up to about twelve hours ahead, the same call reaches into the near future to answer "is it worth waiting?" — turning a flat recommendation into "come back at 6 p.m. and it's two bands cooler." One workhorse endpoint, asked several ways, covers the whole of Decision 1; the segmentation and report endpoints have not entered the picture yet, and for this decision they never will.

## Decision 2: Where to stay

The second decision's core reuses a single endpoint — `create-heatmap` — and it is where the platform's tile structure pays off. Recall that a heatmap request returns temperature as a grid of tiles covering an area. Hotels are points. That mismatch is the whole trick: cover a district with one polygon, fire one `create-heatmap` call, and every tile comes back carrying a temperature. Each hotel then finds its own value with a local point-in-polygon lookup against those tiles — free, instant, no network. Rank the hotels by their values and the district has a **Neighbourhood Heat Score**.

The consequence is the line worth remembering: **the API cost is O(1) in the number of hotels.** One call scores five hotels or fifty; the fiftieth pin costs nothing the first didn't already pay for, because scoring is a loop over tiles the system already holds, not a fan-out of new calls. The hotels themselves come from OpenStreetMap, queried through **Overpass** for `tourism=hotel` inside the district — free, with no booking partner or paid place data — and de-duplicated by proximity, since OSM sometimes lists both a node and a building outline for one hotel.

Four measurements make up the score, each a `create-heatmap` job over the same district polygon, asked a different way:

| Component      | How it's measured         | Why it's in the score                                                         |
| -------------- | ------------------------- | ----------------------------------------------------------------------------- |
| **Night heat** | `tcm`, 00:00–05:00        | Whether the area cools down after dark — the true urban-heat-island signature |
| Day heat       | `tcm`, 10:00–17:00        | Straightforward daytime exposure                                              |
| Hot hours      | `exceedance` above 35 °C  | Total heat exposure across the day                                            |
| Unbroken heat  | `persistence` above 35 °C | The longest stretch with no relief                                            |

Night heat is the component to lead with, because it fills a genuine gap in every other travel tool. Weather apps show the daytime high; almost none show that a district never cools off after dark — which is exactly what an urban heat island _is_, and it is what decides whether an evening walk is bearable and whether you sleep well. Two hotels four hundred metres apart can share an identical daytime high and diverge sharply by 2 a.m.: one drops to 26 °C, while the other, ringed by parking and concrete, never falls below 33 °C. That contrast is invisible on a forecast and obvious in this score.

The four combine into one number by a weighted sum — night heat 35%, hot hours 25%, unbroken heat 20%, day heat 20% — but those weights are a **product choice, not a standard**, and the UI says so. They are a defensible default, not a claim about the world, and the next section is careful about which parts of this score are which.

Three rules keep the score honest, and each blocks a tempting embellishment. First, **rank within the candidate set; do not mint an absolute score.** "The coolest 20% of hotels in this district" is a claim the data can back; "78 out of 100" invents precision the tiles don't carry. The output is an ordering with percentiles, not a grade. Second, **always show the components beside the rank** — the actual temperatures, with units, not a bare sorted list — so a user, or a judge, can see why a hotel placed where it did. Third, **respect the tile resolution.** Tiles run roughly 60–100 m across, so two hotels on the same block land in the same tile and score identically. That is the resolution limit, not a bug: show ties as ties, and never fabricate an order between hotels the data cannot separate.

The score ships as a ladder of tiers — invariant 2 made concrete. Each rung costs more than the last, none of it runs until the user asks, and the base rung works on a Basic plan:

| Tier        | Added cost                                    | What it adds                                                                                                          |
| ----------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 1           | 4 `create-heatmap` jobs, any number of hotels | The full ranked list with its components                                                                              |
| 2           | Free                                          | Tile lookup, percentiles, custom re-weighting — all local math                                                        |
| 3           | 1 `environmental-parameters` call per hotel   | Heat index, humidity, wet-bulb for the top few hotels, on request                                                     |
| 4 (Premium) | 1 job per hotel                               | Satellite canopy % (`satellite-view-segmentation`) and a street-level hero image (`street-view-segmentation`), on tap |

The whole district is ranked at Tier 1 for four jobs, full stop. Everything the user does next — re-sorting, re-weighting, drilling into one hotel's humidity, pulling a canopy figure — either costs nothing or costs a single job for a single hotel they explicitly picked. The paid image endpoints surface only at Tier 4, only on Premium, and only on a tap; they enrich a choice the user has already narrowed, and they never sit between the user and their first ranked list.

## Decision 3: How to get there

This is the branchy decision, and every invariant fires inside it. The user has a visit hour from Decision 1 and a starting point; the job is a walking route to the landmark that trades a little distance for real shade — but only when the heat makes that trade worth computing. The flow is five steps, and each one is doing the work of a specific invariant:

1. **Fetch candidate routes — once.** Ask **OSRM** (the Open Source Routing Machine, running on the same OpenStreetMap data, free to self-host) for three or four alternative walking routes between the two points. This is the only routing call in the entire request; every step below reuses this result set, and none of them queries OSRM again. _(Invariant 1.)_
2. **Classify the walk as short or long.** Read the shortest route's distance. Under roughly 1.5–2 km, one heat reading fairly represents the whole walk, so reuse the landmark's cached curve from Decision 1 at the chosen hour — no new call. Longer than that, the walk crosses too much ground for a single point to speak for it, so fire one `create-heatmap` over the route's **corridor** — a polygon wrapping the path — and take the **maximum** tile value along it, never the mean. _(Invariant 3.)_
3. **Gate on the threshold.** Compare that reading to the comfort threshold. If it is mild, the walk is pleasant however you route it: show the shortest route, say "the weather's fine," and stop — no shade computation, no further cost. Only if it is hot does the flow continue. _(Invariant 2: the free check that gates the expensive work.)_
4. **Score shade on every route — for free.** When it is hot, compute a shaded-street percentage for each route already in hand, from sun geometry and building heights alone. No API call, no imagery. The mechanics are the next section. _(Invariant 4.)_
5. **Rank and present.** Order the routes by shade and show the shortest and the shadiest side by side, each with its number attached — "82% shaded at 4 p.m." — so the user picks with the reason visible, the same discipline the hotel score follows.

### Computing shade

The shade score is pure geometry, built from three inputs, all free:

- **Sun position** — the sun's azimuth (its compass bearing) and elevation (its angle above the horizon) at the route's location and the user's exact visit hour. This is deterministic astronomy: the NOAA solar-position algorithm returns an exact answer for any latitude, longitude, date, and time, with nothing to fetch.
- **Street bearing** — the compass direction of each street segment, read straight from the route geometry OSRM already returned.
- **Building heights** — the heights of the buildings lining each segment, from OpenStreetMap's `building:levels` or `height` tags (levels × ~3 m when only the level count is present).

Together they answer one concrete question per segment: given where the sun sits and how tall the building between the walker and the sun is, does the walker fall inside its shadow? Summed across a route, that produces a shaded-street percentage — the route's score. It is exact for the hour the user actually intends to walk, and it costs nothing.

It is also the design's single largest bet on data quality, and the doc flags it plainly: the engine assumes OSM carries building heights along the candidate routes. Where those tags are sparse the score degrades, which is why building-height coverage is one of the pre-build checks discussed later — a city that fails it is a city to replace, not to demo on.

### Why not just look at a photo?

The obvious alternative is to fetch a street image and read the shade off it, and `street-view-segmentation` exists to label exactly that kind of imagery. The design rejects it for the shade decision, for three reasons that compound. It labels **objects**, not shadows — it can tell you there is a building and a tree, but not what is currently in shadow. It is **direction-blind**: a building on the north side of an east–west street shades almost nothing, while the same building on the south side shades the whole sidewalk, and a single photo can't tell those apart. And it is **undated** — whatever shadow happens to be in the frame was cast at an unknown moment that has nothing to do with the user's visit hour. Sun geometry has none of these problems: it is exact, direction-aware by construction, and computed for the actual hour. The free method is not a cheaper approximation of the paid one here — it is the more correct method, which is the sharpest form invariant 4 takes.

That verdict is specific to _measuring shade_, not a blanket rejection of segmentation. The endpoints keep two honest jobs. `satellite-view-segmentation` reads **tree canopy** from above — genuine shade that OSM's building data simply doesn't contain — so it can refine the top one or two routes on top of the geometric score, as a paid, optional layer. `street-view-segmentation` supplies a **hero image** of a chosen street for the UI. Both are enrichment, both are the Tier-4 uses the hotel score already reserved them for, and neither is ever a load-bearing input to a decision.

## Personalization

Personalization is a core feature, not a stretch goal, and the reason it earns that status is that it costs nothing and demonstrates restraint. At the start of a trip the app asks one optional question: may we personalize the recommendation? A yes collects two coarse facts — an age group (regular or elderly) and whether the user has a heat-affected health condition, chosen from a general list, never a diagnosis or a medication. That is the entire input.

What it changes is deliberately small. It does not touch any of the logic in the three decisions or spend a single extra call; it shifts **thresholds** only — the comfort-band cutoff in Decision 1, the go/no-go threshold in Decision 3 — and it shifts them by exactly one NOAA band toward caution for the sensitive profile. The temptation is to invent an age-specific offset, "elderly users feel it 3 °C hotter," and the design refuses to: the CDC and WHO establish that older adults are at higher risk without publishing a number to subtract. Shifting one published band earlier expresses the same medical guidance — be more conservative for this group — using only the standard the app already displays, with nothing fabricated and a clean answer when a judge asks where the number came from.

Two guardrails keep the feature defensible. The whole layer is pure local threshold arithmetic, so it stays free and adds no latency to any decision. And the app never claims to give medical advice — it presents general, published guidance behind a visible disclaimer, which is the only honest posture for a tool built on coarse categories rather than a clinical profile.

## The resource ledger

Every external call the system can make, collected in one place. The point of the collection is the **When** column — that is the contract that keeps the cost model true — and the fifth endpoint, the PDF report, appears here for its first and only time.

| Layer                    | Source                                        | Cost        | Latency     | When                                       |
| ------------------------ | --------------------------------------------- | ----------- | ----------- | ------------------------------------------ |
| Landmark hourly comfort  | `create-heatmap` (`tcm`)                      | 1 job       | seconds     | Always; cached per landmark/day            |
| Heat-index breakdown     | `environmental-parameters`                    | 1 job       | seconds     | Always; cached per landmark/day            |
| Heat-hours framing       | `create-heatmap` (`exceedance`/`persistence`) | 1–2 jobs    | seconds     | Always; cached                             |
| Forecast (+12 h)         | `create-heatmap` (future start)               | 1 job       | seconds     | Always; cached                             |
| Neighbourhood Heat Score | `create-heatmap` (district polygon)           | 4 jobs      | seconds     | Per district; O(1) in hotels               |
| Route corridor check     | `create-heatmap` (corridor polygon)           | 1 job       | seconds     | Only when the route is long                |
| Routing alternatives     | OSRM                                          | free        | fast        | Once per request                           |
| Sun position + shade     | local math + OSM heights                      | free        | instant     | Only when the heat gate is exceeded        |
| Tree canopy              | `satellite-view-segmentation`                 | 1 job/point | seconds     | Premium; optional; top 1–2 routes          |
| Street hero image        | `street-view-segmentation`                    | 1 job       | seconds+    | Premium; on tap; UI only                   |
| PDF report               | `heat-intelligence`                           | 1 job       | **minutes** | On demand; Premium; never on the live path |

Read down the latency column and the design's central safety property falls out. The only calls that always run are cheap, cached, and measured in seconds. Everything slow is conditional: the corridor check fires solely for long routes, shade is free, canopy and hero images are Premium and user-triggered, and the one job that takes **minutes** — the `heat-intelligence` PDF — runs only on an explicit download, generated in the background. Nothing that can time out ever sits between the user and an answer. That is not a demo trick; it is the reason the demo cannot stall.

## What to verify before building

Some assumptions, when wrong, announce themselves the moment the code runs; others stay silent and surface only in front of the judges. The checks below are sorted by exactly that question — _will I notice while building, or only during the demo?_ — because an hour spent pre-empting a silent failure is well spent and the same hour spent on a loud one is not. Four checks catch silent failures, and they run first, before any feature is built on top of them:

| Gate                           | Check                                                                                                 | If it fails                                                                                                                                   |
| ------------------------------ | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **Coverage**                   | One small `create-heatmap` at the target city returns populated tiles, not empty or `Failed`          | The city isn't covered — every documented example uses US coordinates. Choose a different city before building anything.                      |
| **Timezone**                   | One `environmental-parameters` call; inspect the timestamps and offset in the response                | If `14:00` is read as UTC instead of local, every recommendation shifts silently by the offset and names the wrong hour with full confidence. |
| **Building-height coverage**   | Overpass along a candidate corridor; the share of buildings carrying `building:levels`/`height`       | The shade engine has no data. Above ~70% is sound, 30–70% needs a fallback, below 30% means a different city.                                 |
| **Determinism & ground truth** | Repeat one historical request (it must match); compare one `tcm` value against a known weather source | Confirms the data is correct and stable, not merely that it arrives — and that cached fixtures won't drift from live calls.                   |

Three more checks are not gates but must not be skipped, because each guards a _silent_ correctness bug. The sun-position math is validated against NOAA's solar calculator and confirmed to cast shadows northward at solar noon in the northern hemisphere — a flipped sign convention would invert every shade score without ever raising an error. The NOAA °F→°C conversion is unit-tested at each band boundary (26.7 / 32.2 / 39.4 / 51.7 °C), because those are safety thresholds and an off-by-one-band error is a safety bug. And the full demo is rehearsed once from cached fixtures with networking disabled, as insurance against venue wifi, an exhausted quota, or an API outage during judging.

The remaining feasibility and hardening checks — job latency, plan tier, payload and tile counts, rate limits, error and null-value paths — are real but _loud_: they break visibly while building, so they are handled as they surface rather than front-loaded. This is risk reduction, not a checklist to finish before writing code.

## Scope boundaries

A time-boxed build stays honest by naming what it will not do, and for an implementer these are hard limits, not aspirations to revisit mid-sprint. Each also keeps a claim defensible — the product promises exactly what its data supports and no more:

- **One city, confirmed covered.** The target is a single city or region that passes the coverage gate — not global reach.
- **Routing is consumed, not built.** OSRM, or an equivalent, provides the candidate routes; the project does not implement a routing engine.
- **Shade is computed, never photographed.** Geometric shade from sun position and OSM heights is the only shade input; imagery is never used to detect it.
- **Hotels are ranked on the outdoors only.** The score covers neighbourhood conditions — never room quality, AC, or indoor comfort — and the product carries no booking, pricing, or availability.
- **Personalization stays coarse.** An age group and a general condition flag, nothing clinical; the app offers published guidance behind a disclaimer and never claims to give medical advice.
- **The scope is three questions.** When to visit, where to stay, how to get there — not a full tourism app with landmark catalogs or itineraries.
- **City-wide cool-route search is deferred.** Optimal routing over a whole-city heat graph is future work, described below — not part of this build.

## Risks and contingencies

The four silent-failure gates already cover the risks worth pre-empting up front. What remains are the risks that need a _move_ ready if they land — a pre-decided fallback, so the reaction during a build or a demo is a switch to flip, not a problem to solve under pressure:

| Risk                                                                     | Contingency                                                                                                                             |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| The hourly comfort curve comes back flat from `environmental-parameters` | Fall back to a per-hour `create-heatmap` sweep, cached — more jobs, same curve                                                          |
| The key turns out to be Basic, not Premium                               | Ship anyway: the core product is Basic-safe by design, and only the Tier-4 enrichments go dark                                          |
| OSRM returns no walking alternatives                                     | Generate via-point variants, or switch the routing provider to GraphHopper or Valhalla                                                  |
| Tiles are too coarse to separate nearby hotels                           | Expected, not a failure: request the finest granularity, show ties as ties, and state the resolution in the UI                          |
| Trial credits run out mid-build                                          | A fixture cache is written from the first call onward and every call is logged, so development continues offline                        |
| The whole approach proves unworkable                                     | Fall back to a documented Plan B — a simpler neighbourhood heat dashboard, or a worker heat-safety index — built on the same data layer |

The pattern across the row is the same one that runs through the whole design: the expensive or fragile path always has a cheaper, more robust path behind it, chosen in advance.

## Future work

The route engine as built re-evaluates a handful of routes OSRM already proposed. The ambition beyond it is to stop taking those routes as given: treat the whole city as a graph whose edge weights are heat and shade rather than distance, and run a Weighted A\* search for the coolest path directly, out of thousands of possibilities rather than three or four.

The reason this isn't a hackathon task is not merely time. A correct Weighted A\* needs the weight of every edge _before_ the search begins — thousands of readings, not a handful of candidate routes. The bottleneck is not the search algorithm, which is well understood; it is the cost of collecting weights at that scale. A startup solves it by building a permanent layer the hackathon can't: one batch sweep of the city stored in a geospatial database, refreshed on a schedule instead of per request, after which the search runs entirely on local data and a genuinely optimal cool route becomes fast and cheap.

And here the design's own principle sharpens the vision. The sun-geometry half of that graph needs no API at all — building heights and street geometry already live in OSM, so a city-wide _shade_ graph is computable today, for free, with zero calls. What a paid satellite sweep genuinely adds on top is tree canopy, the one thing OSM lacks. Invariant 4, scaled from one route to a whole city: compute what can be computed, and pay only for what can't. A lighter middle step is achievable even within a hackathon — rank OSRM's alternatives by a free `building:levels` proxy before spending anything — though since the geometric shade score is already free, that pruning mostly decides which one or two routes are worth a _paid_ canopy call, not the shade decision itself.

Other extensions sit further out, all reusing the same core:

- Route personalization by activity — walking, running, cycling — each weighting heat, distance, and crowding differently.
- Proactive alerts built on the +12 h forecast window `create-heatmap` already exposes.
- The same conditional engine pointed at new audiences: delivery workers, outdoor athletes.
- Air-quality data folded into the "best time" decision, especially for the respiratory-condition profile.

## Bottom line

The design is doing its job when three things stay true of the finished build. First, every number the product shows has a one-sentence origin — a NOAA band, a published solar algorithm, a tile the user can point at — and none is a figure the team invented and dressed up as precision. Second, nothing that can time out sits between a user's question and its answer; the slow and the metered are always gated, cached, or one tap away behind a free check. Third, the routes, the shade, and the hotel ranking all trace back to a single fetch and a body of local math, exactly as the invariants require — so if a later change quietly adds a second routing call or averages a corridor's heat, the design has regressed, whatever the feature list says. The strongest single thing to show for all of it remains the Neighbourhood Heat Score: one API call, twenty ranked pins, and an insight — a district that never cools after dark — that no other travel tool puts in front of a traveler.
