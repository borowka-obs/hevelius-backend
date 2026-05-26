# Catalogs

Hevelius comes with several astronomical catalogs. Their use is not mandatory.
You may live without them just fine, but you'll need to use RA/DEC coordinates
all the time.

Catalog data files live in the `catalogs/` directory (see `catalogs/README.md`
for the full list). Common catalogs include NGC, IC, Messier (M), Caldwell (C),
Barnard (B), Sharpless (Sh2), Lynds bright/dark nebulae (LBN, LDN), and others.

## CLI

List catalogs installed in the database (with object counts):

```bash
python bin/hevelius catalogs
python bin/hevelius catalogs --sort name
```

`--sort` may be `entries` (default, by number of objects) or `name`.

Search catalog objects (all filters are optional; combine as needed):

```bash
python bin/hevelius catalog M31
python bin/hevelius catalog --catalog NGC --const Cyg
python bin/hevelius catalog 7000 --catalog NGC
python bin/hevelius catalog --ra "0 42 44" --dec "+41 16 09" --radius 2.0 --limit 5
```

- Positional `name` — partial match on `name` or `altname`.
- `--catalog` — catalog short name (e.g. `NGC`, `M`, `C`).
- `--const` — constellation code (e.g. `Cyg`, `Ori`).
- `--ra` / `--dec` — coordinates (both required together).
- `--radius` — search radius in degrees with `--ra` and `--dec` (default: 1.0).
- `--sort` — `catalog`, `name`, `ra`, `decl`, `const`, `type`, or `magn` (default: `name`).
- `--sort-order` — `asc` or `desc` (default: `asc`).
- `--limit` — cap the number of rows returned.

The REST API exposes the same capabilities (JWT required):

- `GET /api/catalogs` — installed catalogs with object counts (`sort=entries|name`)
- `GET /api/catalogs/list` — search/filter objects with pagination; supports
  `catalog`, `constellation`, `name` (name or altname), `ra`, `decl`, `proximity`,
  `sort_by`, `sort_order`, `page`, `per_page`
- `POST /api/catalogs/list` — same filters in JSON body
- `GET /api/catalogs/search` — quick name/altname search by `query` and `limit`

See `api/openapi.yaml` for request/response schemas.

## Installing catalog data

Files are in `.psql` format. To install them, run your `psql -U hevelius`
client and then use `\i catalogs/filename`. For example, to install the
Messier catalog:

```shell
$ psql -U hevelius
psql (14.6 (Ubuntu 14.6-0ubuntu0.22.04.1), server 12.7 (Ubuntu 12.7-0ubuntu0.20.10.1))
Type "help" for help.

hevelius=> \i catalogs/catalog-messier.psql
DELETE 110
DELETE 1
INSERT 0 1
COPY 110
hevelius=>
```

## Catalog designations

- BN = Bright nebula
- GC = Globular cluster
- OC = Open cluster
- EG = Elliptical (type) galaxy
- DN = Dark nebula
- IG = Irregular galaxy
- PN = Planetary nebula
- SN = Supernova remnant
- SG = Spiral (type) galaxy
- N  = Diffuse Nebula
- SC = Star Cloud
- AS = Asterism
- DS = Double Star
- LG = Lenticular (S0) Galaxy
