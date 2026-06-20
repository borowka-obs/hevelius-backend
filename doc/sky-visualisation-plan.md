# Sky Visualisation — Implementation Plan

## Overview

Add sky visualisation to the project detail page showing the telescope's camera field-of-view (FOV) frame overlaid on a real sky background, centred on the project's RA/Dec target. Projects now store the optical parameters needed for FOV calculation directly, copied from the telescope and sensor at creation time and editable afterwards.

## Scope

- **Backend** (this PR): add `rotation`, `focal`, `resx`, `resy`, `pixel_x`, `pixel_y` to `projects` (schema v23); expose via API — ✅ in progress
- **Frontend** (hevelius-web, follow-up): new Angular component + service, sky map showing all projects, add-project form FOV preview

Tasks are explicitly **out of scope** — the visualisation is based solely on the project's nominal pointing and the stored optical geometry.

---

## Backend changes (schema v23, this PR)

### New columns on `projects`

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `rotation` | `FLOAT` | user input | degrees East of North; NULL = not set |
| `focal` | `FLOAT` | `telescopes.focal` | focal length (mm) |
| `resx` | `INTEGER` | `sensors.resx` | sensor width (pixels) |
| `resy` | `INTEGER` | `sensors.resy` | sensor height (pixels) |
| `pixel_x` | `FLOAT` | `sensors.pixel_x` | pixel pitch X (µm) |
| `pixel_y` | `FLOAT` | `sensors.pixel_y` | pixel pitch Y (µm) |

At project creation time the backend looks up the telescope's attached sensor and copies these values as defaults. They can be overridden via the edit endpoint (e.g. to model a different binning or a reducer/extender). For existing rows the migration fills them in via a `JOIN`.

### FOV calculation (frontend or backend helper)

```
FOV_width_deg  = 2 × arctan( (resx × pixel_x / 1000) / (2 × focal) ) × (180/π)
FOV_height_deg = 2 × arctan( (resy × pixel_y / 1000) / (2 × focal) ) × (180/π)
```

Because `focal`, `resx`, `resy`, `pixel_x`, `pixel_y` are now part of the project object, the frontend needs **no extra API call** to the scopes endpoint for FOV computation.

### API changes

- `GET /api/projects` and `GET /api/projects/{id}` — response includes the five new fields
- `POST /api/projects` — new optional fields `focal`, `resx`, `resy`, `pixel_x`, `pixel_y`; auto-populated from scope's sensor when omitted
- `PATCH /api/projects/{id}` — new optional fields, allowing override after creation

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
| `src/app/models/project.ts` | Add `rotation`, `focal`, `resx`, `resy`, `pixel_x`, `pixel_y` fields |

### 3. `SkyViewComponent` — inputs

```typescript
@Input() ra: number;           // degrees
@Input() dec: number;          // degrees
@Input() fovWidthDeg: number;  // computed from project's stored optical params
@Input() fovHeightDeg: number; // computed from project's stored optical params
@Input() rotation: number;     // degrees East of North; 0 if null
@Input() fovMultiplier = 3;    // how many FOVs wide to show around the target
```

Behaviour:
- Initialises Aladin Lite centred on `ra`/`dec`
- Draws the nominal planned frame as a **dashed rectangle** (colour: white) rotated by `rotation`
- Shows a crosshair at the exact target centre
- Zoom level set so the frame fits comfortably (~ `fovMultiplier × max(fovWidth, fovHeight)`)

### 4. Integration into `ProjectDetailComponent`

Add a "Sky view" card below the project metadata panel. Since FOV params are now on the project object itself, no separate scopes API call is needed.

```typescript
// in project-detail.component.ts
get fovWidthDeg(): number {
  return fovDeg(this.project.resx, this.project.pixel_x, this.project.focal);
}
get fovHeightDeg(): number {
  return fovDeg(this.project.resy, this.project.pixel_y, this.project.focal);
}
function fovDeg(pixels: number, pixelMicron: number, focalMm: number): number {
  return 2 * Math.atan((pixels * pixelMicron / 1000) / (2 * focalMm)) * (180 / Math.PI);
}
```

```html
<!-- in project-detail.component.html -->
<mat-card *ngIf="project">
  <mat-card-header><mat-card-title>Sky view</mat-card-title></mat-card-header>
  <mat-card-content>
    <app-sky-view
      *ngIf="project.focal && project.resx && project.resy; else noFov"
      [ra]="project.ra"
      [dec]="project.decl"
      [fovWidthDeg]="fovWidthDeg"
      [fovHeightDeg]="fovHeightDeg"
      [rotation]="project.rotation ?? 0">
    </app-sky-view>
    <ng-template #noFov>
      <p>No optical parameters — edit the project to set focal length and sensor resolution.</p>
    </ng-template>
  </mat-card-content>
</mat-card>
```

### 5. All-projects sky map

Add a dedicated **Sky map** page (route `/sky-map`) showing all active projects as FOV footprints on a single Aladin view:

- Default sky survey: `P/DSS2/color`
- Each project's footprint drawn as a labelled semi-transparent polygon, coloured by telescope (one hue per `scope_id`)
- Clicking a footprint navigates to that project's detail page
- A filter panel (top) lets the user hide/show projects per telescope
- Projects without optical params (null `focal`/`resx`/`resy`) are shown as crosshairs only

New file: `src/app/components/sky-map/sky-map.component.ts`

The component calls `GET /api/projects` (all pages) and renders footprints using `fovCorners()` (see §7 below).

### 6. Add-project form — FOV preview

Extend `ProjectFormComponent` (or the new-project dialog):

1. When the user picks a **scope** from the dropdown, the form immediately calls `GET /api/scopes/{scope_id}` and fills hidden fields `focal`, `resx`, `resy`, `pixel_x`, `pixel_y` from the returned sensor.
2. An **expandable "Optical parameters" section** shows the auto-populated values in editable inputs so the user can review and override before submitting (e.g. to model binning: set `resx = native_resx / bin`, adjust pixel sizes accordingly).
3. A live **FOV summary chip** below the section reads: `FOV: 1.23° × 0.82°` — recomputes as the user edits any of the five fields.
4. If the scope has no sensor the section shows a "No sensor attached to this telescope" notice and leaves the fields blank (submittable — they are nullable).
5. On submit, all five values are sent in the `POST /api/projects` body alongside `rotation`.

### 7. Project model update

```typescript
// src/app/models/project.ts  (add to existing interface)
rotation?: number | null;
focal?: number | null;
resx?: number | null;
resy?: number | null;
pixel_x?: number | null;
pixel_y?: number | null;
```

### 8. UX details

- Default height of the sky view card: `400px` (CSS fixed, or configurable via input)
- Background survey: default to `P/DSS2/color`; add a small dropdown to switch (2MASS, PanSTARRS, etc.)
- If `rotation` is `null`, treat as `0` (North up) and show a small "(rotation not set)" badge
- The frame rectangle is drawn using Aladin's `A.graphicOverlay()` with a rotated polygon computed from the four corners in WCS space

### 9. Corner coordinate calculation

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

1. ✅ Schema v23 — `rotation` + optical params on `projects` (this PR)
2. ✅ API — expose new fields on all project endpoints (this PR)
3. `npm install aladin-lite` in hevelius-web
4. Update `Project` model with new fields
5. Create `SkyViewComponent` (Aladin init + FOV rectangle overlay)
6. Wire `<app-sky-view>` into `ProjectDetailComponent` using stored params
7. Build `SkyMapComponent` for all-projects view; add route `/sky-map`
8. Extend add-project form with sensor-derived FOV preview
9. Test with a few real projects (Orion Nebula, Crab Nebula, etc.)

---

## Notes

- `rotation` convention: **degrees East of North**, 0–360 (same as FITS `PA` keyword and PixInsight plate-solve output). Values outside 0–360 are accepted by the DB and should be normalised modulo 360 on display.
- The `rotation` field defaults to `NULL` in the DB, not `0`. The frontend should display a small indicator when it is null so users know it hasn't been configured rather than assuming North-up is correct.
- Aladin Lite v3 is ESM-only; use a dynamic `import()` in the Angular component `ngAfterViewInit` to avoid SSR issues.
- Optical params on `projects` are denormalised by design: they represent the imaging setup *as planned for this project*, which may differ from the telescope's current sensor (e.g. if the sensor is later swapped, or the user applies binning).
