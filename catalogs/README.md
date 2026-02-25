# Astronomical catalogs

Catalog data are loaded via `.psql` files.

## New catalogs (generated from CDS/VizieR)

The following catalogs were generated from CDS/VizieR data and can be regenerated with `python3 convert_catalogs.py` (after placing the raw data in `_dl/`).

| Short | Catalog | Source | Records |
|-------|---------|--------|---------|
| B | Barnard (dark objects) | VII/220A | 349 |
| C   | Caldwell | | 109 |
| Ced | Cederblad (bright diffuse Galactic nebulae) | VII/231 | 330 |
| Col | Collinder (open star clusters, updated) | CloudyNights article | 471 |
| NGC | New General Catalog | | 8418 |
| IC  | Index Catalog       | | 4767 |
| LBN | Lynd's Bright Nebulae | VII/9 | 1125 |
| LDN | Lynd's Dark Nebulae | VII/7A | 1791 |
| M   | Messier Catalogue   | | 110 |
| Mel | Melotte (star clusters) | In-The-Sky.org | 245 |
| Sh2 | Sharpless (H II regions) | VII/20 | 313 |
| vdB | van den Bergh (reflection nebulae) | VII/21 | 158 |

### Collinder (Col)

The **Collinder catalogue** is generated from the [CloudyNights article "The Collinder Catalog (updated)"](https://www.cloudynights.com/articles/articles/the-collinder-catalog-updated-r2467/) by Thomas Watson (observer's checklist with coordinates from HCNGC). It is not an official IAU source. To regenerate: save the article HTML as `catalogs/_dl/collinder.html` and run `python3 convert_catalogs.py`.

### Melotte (Mel)

The **Melotte catalogue** (245 objects, 1915) is parsed from the [In-The-Sky.org Melotte catalogue](https://in-the-sky.org/data/catalogue.php?cat=Melotte) with full details (view=1). Save the three pages as `melotte_p1.html`, `melotte_p2.html`, `melotte_p3.html` in `_dl/`, then run the converter.

## Downloading raw data for regeneration

Place the following files in `catalogs/_dl/` before running `convert_catalogs.py`:

- `cederblad.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/231/catalog.dat
- `VII_21_catalog.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/21/catalog.dat
- `VII_20_catalog.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/20/catalog.dat.gz (gunzip to catalog.dat, then rename)
- `VII_9_catalog.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/9/catalog.dat
- `VII_7A_ldn.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/7A/ldn
- `VII_220A_barnard.dat` — https://cdsarc.cds.unistra.fr/ftp/VII/220A/barnard.dat
- `collinder.html` — Save from https://www.cloudynights.com/articles/articles/the-collinder-catalog-updated-r2467/ (for Col catalog)
- `melotte_p1.html`, `melotte_p2.html`, `melotte_p3.html` — From https://in-the-sky.org/data/catalogue.php?cat=Melotte&view=1&page=1 (and page=2, page=3) for Mel catalog
