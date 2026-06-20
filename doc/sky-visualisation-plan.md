# Sky Visualisation — Implementation Plan

## Overview

Add a sky visualisation to the project detail page showing the telescope's camera field-of-view (FOV) frame overlaid on a real sky background, centred on the project's RA/Dec target. The camera rotation angle is the only piece of data that had to be added to the backend (this PR, schema v23); everything else (FOV size, pixel scale) can be derived from existing telescope and sensor data.

## Scope

- **Backend** (this PR): add `rotation` field to `projects` — ✅ done
- **Frontend** (hevelius-web, follow-up): new Angular component + service

Tasks are explicitly **out of scope** — the visualisation is based solely on the project's nominal pointing and the telescope/sensor geometry.

---

## Data available (no further backend changes needed)

| Source | Fields used |
|--------|-------------|
| `Project` | `ra`, `decl`, `rotation`, `scope_id` |
| `GET /api/scopes/{scope_id}` | `focal` (focal length, mm) |
| Scope → sensor | `resx`, `resy` (pixels), `pixel_x`, `pixel_y` (micron/pixel) |

### FOV calculation

```
FOV_width_deg  = 2 × arctan( (resx × pixel_x / 1000) / (2 × focal) ) × (180/π)
FOV_height_deg = 2 × arctan( (resy × pixel_y / 1000) / (2 × focal) ) × (180/π)
```

All values already present in the existing API. No new backend endpoint needed.

---

## Frontend plan (hevelius-web)

### 1. Sky rendering library

Use **[Aladin Lite v3](https://aladin.cds.unistra.fr/ADE/aladinLiteV3.gml)** — the standard for web-based interactive sky charts. It provides:
- DSS / PanSTARRS / 2MASS background sky imagery
- Overlay API for drawing custom shapes (rectangles, polygons)
- Native zoom and pan
- Install: `npm install aladin-lite` (or load from CDN)

### 2. New files

| File | Description |
|------|-------------|
| `src/app/components/sky-view/sky-view.component.ts` | Main visualisation component |
| `src/app/components/sky-view/sky-view.component.html` | Template (single `<div>` host for Aladin) |
| `src/app/components/sky-view/sky-view.component.scss` | Styles |
| `src/app/services/footprints.service.ts` | Data-fetching service (scope + sensor) |
| `src/app/models/project.ts` | Add `rotation?: number \| null` field |

### 3. `SkyViewComponent` — inputs

```typescript
@Input() ra: number;           // degrees
@Input() dec: number;          // degrees
@Input() fovWidthDeg: number;  // computed from sensor + focal
@Input() fovHeightDeg: number; // computed from sensor + focal
@Input() rotation: number;     // degrees East of North; 0 if null
@Input() fovMultiplier = 3;    // how many FOVs wide to show around the target
```

Behaviour:
- Initialises Aladin Lite centred on `ra`/`dec`
- Draws the nominal planned frame as a **dashed rectangle** (colour: white) rotated by `rotation`
- Shows a crosshair at the exact target centre
- Zoom level set so the frame fits comfortably (~ `fovMultiplier × max(fovWidth, fovHeight)`)

### 4. Integration into `ProjectDetailComponent`

Add a "Sky view" card below the project metadata panel. The card:
1. Calls `GET /api/scopes/{scope_id}` (already used elsewhere — reuse `ScopesService`)
2. Computes FOV from sensor data
3. Passes results into `<app-sky-view>`
4. Shows a spinner while loading; shows a "No telescope/sensor data" notice if the scope has no sensor

```html
<!-- in project-detail.component.html -->
<mat-card *ngIf="project">
  <mat-card-header><mat-card-title>Sky view</mat-card-title></mat-card-header>
  <mat-card-content>
    <app-sky-view
      [ra]="project.ra"
      [dec]="project.decl"
      [fovWidthDeg]="fovWidth"
      [fovHeightDeg]="fovHeight"
      [rotation]="project.rotation ?? 0">
    </app-sky-view>
  </mat-card-content>
</mat-card>
```

### 5. Project model update

```typescript
// src/app/models/project.ts  (add to existing interface)
rotation?: number | null;
```

### 6. UX details

- Default height of the sky view card: `400px` (CSS fixed, or configurable via input)
- Background survey: default to `P/DSS2/color`; add a small dropdown to switch (2MASS, PanSTARRS, etc.)
- If `rotation` is `null`, treat as `0` (North up) and show a small "(rotation not set)" badge
- The frame rectangle is drawn using Aladin's `A.graphicOverlay()` with a rotated polygon computed from the four corners in WCS space

### 7. Corner coordinate calculation

To draw the rotated rectangle, compute the four corners from the centre:

```typescript
function fovCorners(ra: number, dec: number,
                    wDeg: number, hDeg: number,
                    rotDeg: number): [number, number][] {
  const rotRad = rotDeg * Math.PI / 180;
  const hw = wDeg / 2, hh = hDeg / 2;
  // half-widths in RA (account for cos(dec) projection)
  const cosD = Math.cos(dec * Math.PI / 180);
  const corners = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
  return corners.map(([dx, dy]) => {
    const rx =  dx * Math.cos(rotRad) + dy * Math.sin(rotRad);
    const ry = -dx * Math.sin(rotRad) + dy * Math.cos(rotRad);
    return [ra + rx / cosD, dec + ry];
  });
}
```

Pass the result to `A.polygon(corners)` in the Aladin overlay.

---

## Implementation order

1. `npm install aladin-lite` in hevelius-web
2. Update `Project` model with `rotation`
3. Create `SkyViewComponent` (Aladin init + FOV rectangle overlay)
4. Add FOV computation logic to `ProjectDetailComponent` (reuse existing scope service call)
5. Wire `<app-sky-view>` into the project detail template
6. Test with a few real projects (Orion Nebula, Crab Nebula, etc.)

---

## Notes

- `rotation` convention: **degrees East of North**, 0–360 (same as FITS `PA` keyword and PixInsight plate-solve output). Values outside 0–360 are accepted by the DB and should be normalised modulo 360 on display.
- The `rotation` field defaults to `NULL` in the DB, not `0`. The frontend should display a small indicator when it is null so users know it hasn't been configured rather than assuming North-up is correct.
- Aladin Lite v3 is ESM-only; use a dynamic `import()` in the Angular component `ngAfterViewInit` to avoid SSR issues.
