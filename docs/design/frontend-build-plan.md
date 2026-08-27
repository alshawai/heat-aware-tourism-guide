# Frontend-Only Implementation Plan

## Status and scope

This plan covers the React/Vite single-page application described in the frontend build prompt. The implementation is frontend-only and must run without FastAPI or any external provider credentials.

This work is larger than the original scaffold acceptance criteria in GitHub Issue #8. Issue #8 establishes the runnable React/Vite foundation; the feature flow below builds the complete mock-driven frontend on that foundation. Before committing, we should decide whether to keep all work under Issue #8 or create a follow-up issue for the full product flow.

### In scope

- Welcome screen with two independent feature paths.
- Plan-a-walk flow.
- Rank-hotels flow.
- Shared location picker with search and map-click behavior.
- Local Promise-based mock data with artificial latency.
- Loading, success, degraded, empty, and error states.
- Per-result provenance.
- Responsive and accessible UI.
- Frontend tests and production build validation.

### Out of scope

- FastAPI and API implementation.
- Calls to FortyGuard, OSRM, Overpass, or any other live data provider.
- Authentication, booking, hotel pricing, and availability.
- Multi-language support.
- Claims that a route is globally optimal or that modeled shade is measured shade.

## Current-state cleanup

The current frontend is a single `frontend/src/main.jsx` component that:

- hardcodes place names and coordinates;
- sends a request to `/api/heatmap`;
- combines input, loading, and result rendering on one page; and
- does not implement either required multi-screen flow.

We will replace this proof-of-concept screen rather than extend it. We will preserve the Vite scaffold, update dependencies intentionally, and keep the frontend runnable with `npm run dev` from `frontend/`.

## Technical decisions

### Language and application structure

- Convert the frontend source from JSX to TypeScript/TSX because the required mock contracts use `.ts` files and typed response shapes will make later API integration safer.
- Use React Router for an explicit route-based state machine.
- Keep cross-screen selections in a small React context plus reducer.
- Keep request lifecycle state local to each result screen so screens read only the state they need.
- Do not add a global provenance footer; each result screen supplies provenance to a shared presentation component.
- Keep all user-visible location, hotel, and landmark names in selected-location state or mock scenario data.

### Data-access boundary

Screens will not import mock scenario objects directly. They will call a small data-client interface, for example:

- `analyzeTrip(request)`
- `rankHotels(request)`

During this phase, `src/services/dataClient.ts` exports the mock implementation. Later, changing that export to a live implementation will replace the data source without rewriting screens or result components.

### Map approach

- Build map interaction behind a reusable `MapView` interface.
- Use the same `LocationPicker` component in both feature flows.
- Search suggestions and selectable map points come from local mock location data.
- Map clicks produce a coordinate and resolve a display label from mock data; no city name is used as a component default.
- If remote map tiles are used for visual context, the feature must remain usable when tiles are unavailable. No product data may depend on tile requests.
- Route geometries and hotel markers come only from mock responses.

## Proposed frontend structure

```text
frontend/src/
├── app/                 # router, app shell, state context, reducer
├── components/          # shared UI and state presentations
├── features/
│   ├── walk/            # walk screens and feature-specific components
│   └── hotels/          # hotel screens and feature-specific components
├── mocks/               # scenarios, Promise-based mock fetchers, edge cases
├── services/            # data-client interface and selected implementation
├── types/               # request, response, provenance, and UI-state types
├── styles/              # tokens, layout, components, responsive rules
├── test/                # test setup and reusable test factories
└── main.tsx              # Vite entry point
```

## Route/state machine

### Shared routes

| Route | Screen             | Required state |
| ----- | ------------------ | -------------- |
| `/`   | Welcome            | None           |
| `*`   | Not found/recovery | None           |

### Plan-a-walk routes

| Route                   | Screen           | Required state       | Next action                    |
| ----------------------- | ---------------- | -------------------- | ------------------------------ |
| `/walk/location`        | Pick a location  | None                 | Save selected destination      |
| `/walk/date`            | Choose a date    | Destination          | Save date and request analysis |
| `/walk/result`          | Best time result | Destination and date | Open route comparison          |
| `/walk/routes`          | Compare routes   | Trip analysis        | Select one returned route      |
| `/walk/routes/:routeId` | Route selected   | Selected route       | Show turn-by-turn details      |

### Rank-hotels routes

| Route              | Screen          | Required state             | Next action                            |
| ------------------ | --------------- | -------------------------- | -------------------------------------- |
| `/hotels/location` | Pick a location | None                       | Save selected area and request ranking |
| `/hotels/results`  | Hotels ranked   | Selected area              | Select a hotel                         |
| `/hotels/:hotelId` | Hotel detail    | Ranking and selected hotel | Adjust local weights or return         |

### Route guards

- A screen missing required state redirects to the nearest valid step.
- Browser back/forward navigation remains functional.
- Starting either feature resets only that feature's transient state.
- Retry repeats the last request without discarding valid user input.
- Reload behavior is documented and tested; small serializable selections may be stored in session storage if needed.

## Domain contracts

Define TypeScript contracts before building result components.

### Shared contracts

- `LocationSelection`: generated ID, display name, coordinates, optional context label.
- `ResultState`: `idle | loading | success | degraded | empty | error`.
- `Provenance`: source mode, data date, confidence, coverage, and optional note.
- `Metric`: value, unit, provider/product label, and whether an actual heat index is available.
- `MockMode`: `success | degraded | empty | error`.

### Trip-analysis response

`mockTripAnalyze.ts` will mirror the eventual `POST /api/trip/analyze` response and include:

- request/scenario identity;
- hourly heat or comfort series;
- metric name and units;
- best-time recommendation and reason;
- route alternatives;
- route geometry and turn-by-turn steps;
- distance and duration;
- heat status;
- modeled shade estimate;
- shade/building-data coverage and confidence; and
- independent provenance for best-time and route results.

### Hotel-ranking response

`mockHotelRanking.ts` will include:

- selected area;
- ranking-level provenance;
- weighting configuration;
- usable and discovered hotel counts;
- ranked hotels;
- percentile and tie information;
- per-component raw values and normalized contributions; and
- enough component information for local re-weighting without another fetch.

## Mock data plan

### Named scenarios

Create at least three location-neutral-in-code scenarios. All proper place names live in mock files.

1. **Full scenario**
   - Many hotels.
   - No ranking ties.
   - Several route alternatives.
   - Strong route coverage/confidence.
   - Actual heat index available so NOAA Heat Index labeling is valid.

2. **Tied/few-hotels scenario**
   - Fewer than five usable hotels.
   - At least one ranking tie.
   - Multiple route alternatives.
   - Provider metric only, clearly labeled as non-NOAA.
   - Degraded ranking provenance.

3. **Limited-route scenario**
   - One returned route although several were requested.
   - Weak building-height coverage.
   - Modeled shade shown with low-confidence language.
   - No implication that the route is globally optimal.

Each scenario will have a distinct selected location, date, hourly shape, hotel count, and route shape. Component code will receive these values through props/state and will contain no named place defaults.

### Development edge-case controls

Add a development-only scenario/state control that can select:

- named scenario;
- success;
- degraded/partial;
- empty/unavailable; or
- error.

Also support query parameters such as `?scenario=<id>&state=degraded` so every state is directly reviewable and testable. Hide the visual control in production builds, while keeping deterministic test hooks in the mock client.

### Mock request behavior

- Every mock fetch returns a Promise.
- Each request resolves or rejects after a deterministic 1–3 second `setTimeout` delay.
- Requests support cancellation through `AbortSignal` to avoid state updates after navigation.
- Empty mode resolves to an explicit unavailable result rather than an accidental empty success.
- Error mode rejects with a typed, non-technical UI-safe error category.
- Retry reuses the same request and selected development mode.

## Shared components

### `AppShell`

- Product identity and compact navigation.
- Current feature context and back action.
- No city, hotel, or landmark names in static copy.

### `LocationPicker`

- Shared unchanged between walk and hotel flows.
- Search input with keyboard-accessible local suggestions.
- Interactive map area with click selection.
- Selected coordinates and selected display name confirmation.
- Validation before continuing.
- Empty search and unknown-map-point handling.

### `ProvenanceFooter`

Reusable presentation pattern, instantiated independently by each result screen with screen-specific values:

- source (`mock` or `fixture` in this phase);
- data date;
- confidence;
- coverage where relevant; and
- a concise limitation/note.

### Result-state components

- `ResultSkeleton`: content-shaped skeletons, not spinner-only UI.
- `DegradedNotice`: visible explanation of what is incomplete and what remains usable.
- `UnavailableState`: scenario-specific no-data message and a path back.
- `ErrorState`: non-technical message and retry button.

### Supporting components

- Metric label/badge that distinguishes actual NOAA Heat Index from provider metrics.
- Hourly series/chart with a text/table equivalent.
- Route map and synchronized route cards.
- Hotel ranking card and component breakdown.
- Weight controls with percentages and reset action.
- Coverage/confidence indicator with text, not color alone.

## Screen implementation plan

### 1. Welcome

- Explain the two decisions without assuming a location.
- Provide separate actions for Plan a walk and Rank hotels.
- Keep the paths independent.

### 2. Walk location

- Render the shared `LocationPicker`.
- Save the selected destination.
- Do not prefill a named city or landmark in component state.

### 3. Walk date

- Display the selected destination from state.
- Validate the selected date.
- Submit through `dataClient.analyzeTrip` and navigate to the result route.

### 4. Best-time result

Handle all five states independently:

- loading: recommendation and chart skeletons;
- success: hourly series, correctly labeled metric, recommendation, and reason;
- degraded: usable series plus a clear data limitation;
- empty: no matching fixture/scenario message;
- error: non-technical failure and retry.

Render best-time-specific provenance. Do not call provider temperature a NOAA Heat Index unless the response says an actual heat index is available.

### 5. Route comparison

- Request/read returned alternatives only.
- Draw every returned alternative and synchronize map selection with route cards.
- Show distance, duration, heat status, modeled shade estimate, and coverage/confidence.
- Use “best among returned alternatives” language.
- Describe shade as a modeled estimate based on building data.
- Treat one route as a valid degraded comparison, not a crash or fabricated set.
- Render route-specific provenance.

### 6. Route selected

- Show the selected route summary and turn-by-turn steps.
- Preserve modeled-shade and returned-alternatives qualifications.
- Provide a route-comparison back action.

### 7. Hotel ranking

Handle all five states independently:

- loading: list/card skeletons;
- success: ranked list, percentile, ties, components, and weighting configuration;
- degraded: fewer than five usable hotels or incomplete component coverage;
- empty: no matching fixture or no usable hotels;
- error: non-technical failure and retry.

Do not present a bare objective “score out of 100.” Render hotel-ranking-specific provenance.

### 8. Hotel detail

- Show raw component values and weighted contributions.
- Show percentile and tie information.
- Provide local weight controls whose values must total 100%.
- Recalculate ranking locally from response components.
- Label weights as configurable product preferences, not scientific truth.
- Provide reset-to-default behavior.

## Visual and interaction design

- Keep the existing warm/green visual direction only as a starting point; replace single-hero layout rules with reusable screen layouts.
- Design mobile-first with clear desktop enhancements.
- Keep maps, charts, route lines, cards, and controls readable at narrow widths.
- Use consistent spacing, typography, status colors, and focus treatment through CSS custom properties.
- Make loading skeletons visibly match each result layout.
- Make degraded, empty, and error states visually distinct with icons/text structure, not color alone.
- Respect reduced-motion preferences.

## Accessibility requirements

- Semantic headings and landmarks on every screen.
- Visible keyboard focus.
- Fully keyboard-operable search suggestions and controls.
- Labels and instructions for date, search, and weight inputs.
- `aria-live` announcements for asynchronous status changes.
- Text alternatives or tabular summaries for charts and map-derived comparisons.
- Sufficient color contrast.
- Route and confidence distinctions never conveyed only by color.

## Testing plan

### Unit tests

- Reducer transitions and route guards.
- Mock scenario selection and delayed Promise behavior with fake timers.
- Metric labeling, especially non-NOAA provider metrics.
- Hotel percentile/tie rendering.
- Local re-weighting calculations and total-weight validation.
- Route recommendation wording.
- Provenance rendering.

### Component tests

- Shared `LocationPicker` behaves the same in both flows.
- Every result screen renders loading, success, degraded, empty, and error states.
- Retry invokes the request again.
- One-route and weak-coverage scenarios remain usable.
- Few-hotel and tied rankings remain understandable.
- No result screen depends on a global provenance footer.

### Flow tests

- Welcome → walk location → date → best time → routes → selected route.
- Welcome → hotel location → ranking → detail → re-weighting.
- Back/forward behavior and missing-state redirects.
- Query-parameter edge-case selection.

### Static checks

- Search component source and static copy for mock-only place names to prevent accidental hardcoding.
- TypeScript type check.
- Formatting/linting.
- Production Vite build.

## Implementation sequence

### Phase 1 — Foundation

1. Confirm whether this full plan remains in Issue #8 or moves to a follow-up issue.
2. Add TypeScript, router, map, and frontend test dependencies.
3. Convert the Vite entry point to TypeScript.
4. Create app shell, router, feature state context/reducer, design tokens, and route guards.
5. Remove the current `/api/heatmap` call and all hardcoded place copy from component code.

### Phase 2 — Contracts and mocks

1. Define shared request/response types.
2. Add at least three named scenario datasets.
3. Implement delayed and cancellable mock fetch functions.
4. Add success/degraded/empty/error selection through dev controls and query parameters.
5. Add the data-client seam for future live calls.

### Phase 3 — Shared input flow

1. Build and test `LocationPicker`.
2. Build welcome and both location routes.
3. Add date selection and validation for the walk flow.
4. Verify all displayed place names originate from selection or mock data.

### Phase 4 — Walk results

1. Build best-time state presentations and hourly series.
2. Build route comparison map/cards and all edge states.
3. Build selected-route turn-by-turn view.
4. Add independent provenance to best-time and route screens.

### Phase 5 — Hotel results

1. Build ranking list, percentile, ties, component breakdown, and all edge states.
2. Build hotel detail.
3. Implement local re-weighting and deterministic re-ranking.
4. Add independent hotel-ranking provenance.

### Phase 6 — Quality and delivery

1. Complete responsive and accessibility review.
2. Add unit, component, and flow tests.
3. Verify every state through the dev selector/query parameters.
4. Run formatting, linting, type checking, tests, and production build.
5. Update run documentation to state clearly that this phase needs no backend.

## Definition of done

- `npm run dev` from `frontend/` starts the complete mock-driven SPA.
- No backend process or provider credential is required.
- Welcome exposes both independent feature flows.
- Every screen is a separate routed component.
- Both feature paths reuse the same `LocationPicker`.
- No named city, hotel, or landmark appears in component code, static copy, or default state.
- At least three named mock scenarios exercise varied dates, locations, hotel counts, ties, metrics, and route counts.
- Mock requests take 1–3 seconds and expose meaningful skeleton loading states.
- Best-time, hotel-ranking, and route-comparison screens each support loading, success, degraded, empty, and error states.
- Each result screen renders its own source, date, confidence, and relevant coverage provenance.
- Provider metrics are never silently labeled as NOAA Heat Index.
- Route language says “best among returned alternatives,” never globally optimal.
- Shade language says it is a modeled estimate based on building data.
- Hotel results expose components, percentile, ties, and weights rather than an objective bare score.
- Desktop and mobile flows are usable with keyboard and screen-reader-friendly semantics.
- Frontend type checks, tests, and production build pass.

## Local verification commands

From the `frontend/` directory:

```bash
npm install
npm run dev
```

Before considering the implementation complete:

```bash
npm run build
```

Additional lint, type-check, and test commands will be added to `frontend/package.json` when their tools are introduced in Phase 1.
