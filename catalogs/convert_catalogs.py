#!/usr/bin/env python3
"""
Convert CDS/VizieR catalog data to hevelius catalog SQL format.
Reads from catalogs/_dl/ and writes COPY lines for objects (name, ra, decl, descr, comment, type, epoch, const, magn, x, y).
RA in decimal hours, Dec in decimal degrees. Uses \\N for NULL.
"""
from pathlib import Path
import math
import re

DL = Path(__file__).parent / "_dl"
NULL = "\\N"


# Galactic to equatorial (J2000) in degrees. NGP, l_CP from standard values.
def gal2eq_deg(l_deg, b_deg):
    """Convert galactic l,b (degrees) to equatorial RA,Dec (degrees). J2000."""
    lon_rad = math.radians(l_deg)
    b = math.radians(b_deg)
    # J2000 north galactic pole
    ra_ngp = math.radians(192.859508)
    dec_ngp = math.radians(27.128336)
    l_ncp = math.radians(122.931918)
    sin_dec = math.sin(b) * math.sin(dec_ngp) + math.cos(b) * math.cos(dec_ngp) * math.cos(lon_rad - l_ncp)
    dec_rad = math.asin(max(-1, min(1, sin_dec)))
    y = math.cos(b) * math.sin(lon_rad - l_ncp)
    x = math.cos(b) * math.cos(dec_ngp) * math.cos(lon_rad - l_ncp) - math.sin(b) * math.sin(dec_ngp)
    ra_rad = math.atan2(y, x) + ra_ngp
    ra_deg = math.degrees(ra_rad) % 360
    dec_deg = math.degrees(dec_rad)
    return ra_deg, dec_deg


def ra_deg_to_hours(ra_deg):
    return ra_deg / 15.0


def row(*fields, catalog=None):
    """Row for COPY: name, ra, decl, descr, comment, type, epoch, const, magn, x, y [, catalog]."""
    parts = [str(f) if f is not None else NULL for f in fields]
    if catalog is not None:
        parts.append(catalog)
    return "\t".join(parts)


def parse_cederblad():
    """VII/231: Cederblad. RA/Dec B1900 in catalog.dat. Bytes 1-3 Ced, 4 letter, 6-16 Name, 17-18 RAh, 20-23 RAm, 25 DE-, 26-27 DEd, 29-30 DEm."""
    lines = []
    p = DL / "cederblad.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 31:
            continue
        try:
            ced = line[0:3].strip()
            letter = (line[3:4] or " ").strip()
            rah = int(line[16:18].strip() or 0)
            ram = float(line[19:23].strip() or 0)
            de_sign = (line[24:25] or "+").strip() or "+"
            if de_sign == ":":
                de_sign = "+"
            ded = int(line[25:27].strip() or 0)
            dem = int(line[28:30].strip() or 0)
        except (ValueError, IndexError):
            continue
        if not ced or not ced.isdigit():
            continue
        name = f"Ced {ced}{letter}" if letter else f"Ced {ced}"
        ra_h = rah + ram / 60.0
        dec_deg = (1 if de_sign == "+" else -1) * (ded + dem / 60.0)
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Nb", NULL, NULL, NULL, NULL, NULL, catalog="Ced"))
    return lines


def parse_vdb():
    """VII/21: van den Bergh. Only galactic coords in catalog.dat. Bytes 2-4 VdB, 6-15 DM, 25-29 oGLON, 30-34 oGLAT."""
    lines = []
    p = DL / "VII_21_catalog.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 35:
            continue
        try:
            vdb = line[1:4].strip()
            if not vdb or not vdb.isdigit():
                continue
            glon = float(line[24:29].strip() or 0)
            glat = float(line[29:34].strip() or 0)
        except (ValueError, IndexError):
            continue
        ra_deg, dec_deg = gal2eq_deg(glon, glat)
        ra_h = ra_deg_to_hours(ra_deg)
        name = f"vdB {vdb}"
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Nb", NULL, NULL, NULL, NULL, NULL, catalog="vdB"))
    return lines


def parse_sharpless():
    """VII/20: Sharpless. catalog.dat bytes 1-4 Sh2, 21-22 RAh 1900, 23-24 RAm, 25-27 RAds (0.1s), 28 DE-, 29-30 DEd, 31-32 DEm, 33-34 DEs."""
    lines = []
    p = DL / "VII_20_catalog.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 34:
            continue
        try:
            sh2 = line[0:4].strip()
            if not sh2 or not sh2.isdigit():
                continue
            rah = int(line[20:22].strip() or 0)
            ram = int(line[22:24].strip() or 0)
            rads = int(line[24:27].strip() or 0)  # in 0.1s
            de_sign = line[27:28] or "+"
            ded = int(line[28:30].strip() or 0)
            dem = int(line[30:32].strip() or 0)
            des = int(line[32:34].strip() or 0)
        except (ValueError, IndexError):
            continue
        ra_h = rah + ram / 60.0 + (rads / 10.0) / 3600.0
        dec_deg = (1 if de_sign == "+" else -1) * (ded + dem / 60.0 + des / 3600.0)
        name = f"Sh2-{sh2}"
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Nb", NULL, NULL, NULL, NULL, NULL, catalog="Sh2"))
    return lines


def parse_lbn():
    """VII/9: Lynds Bright. catalog.dat bytes 2-5 Seq, 21-22 RAh 1950, 24-25 RAm, 28 DE-, 29-30 DEd, 32-33 DEm."""
    lines = []
    p = DL / "VII_9_catalog.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 34:
            continue
        try:
            seq = line[1:5].strip()
            if not seq or not seq.isdigit():
                continue
            rah = int(line[20:22].strip() or 0)
            ram = int(line[23:25].strip() or 0)
            de_sign = line[27:28] or "+"
            ded = int(line[28:30].strip() or 0)
            dem = int(line[31:33].strip() or 0)
        except (ValueError, IndexError):
            continue
        ra_h = rah + ram / 60.0
        dec_deg = (1 if de_sign == "+" else -1) * (ded + dem / 60.0)
        name = f"LBN {seq}"
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Nb", NULL, NULL, NULL, NULL, NULL, catalog="LBN"))
    return lines


def parse_ldn():
    """VII/7A: Lynds Dark. ldn file bytes 1-4 LDN, 6-7 RAh 1950, 9-12 RAm, 16 DE-, 17-18 DEd, 20-21 DEm."""
    lines = []
    p = DL / "VII_7A_ldn.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 22:
            continue
        try:
            ldn = line[0:4].strip()
            if not ldn or not ldn.isdigit():
                continue
            rah = int(line[5:7].strip() or 0)
            ram = float(line[8:12].strip() or 0)
            de_sign = line[15:16] or "+"
            ded = int(line[16:18].strip() or 0)
            dem = int(line[19:21].strip() or 0)
        except (ValueError, IndexError):
            continue
        ra_h = rah + ram / 60.0
        dec_deg = (1 if de_sign == "+" else -1) * (ded + dem / 60.0)
        name = f"LDN {ldn}"
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Dn", NULL, NULL, NULL, NULL, NULL, catalog="LDN"))
    return lines


def parse_collinder():
    """CloudyNights Collinder (updated) from collinder.html. Table: Col #, NGC/Other, Con, RA, DEC, m, #Stars, Size, Class, n."""
    lines = []
    p = DL / "collinder.html"
    if not p.exists():
        return lines
    html = p.read_text(encoding="utf-8", errors="replace")
    # Find table body rows: <tr><td>N</td>...
    row_re = re.compile(
        r"<tr><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>"
        r"<td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>"
        r"<td>([^<]*)</td><td>(.*?)</td></tr>",
        re.DOTALL,
    )
    for m in row_re.finditer(html):
        col_num_raw, ngc, con, ra_s, dec_s, mag_s, nstars, size, cls, n_ref = m.groups()
        # Col # can be "1" or "463 (20a)" - use first number
        col_match = re.match(r"^(\d+)", col_num_raw.strip())
        if not col_match:
            continue
        col_num = col_match.group(1)
        name = f"Col {col_num}"
        # Strip HTML from con (e.g. &nbsp;)
        con = con.replace("&nbsp;", "").strip() or None
        if con and len(con) > 3:
            con = con[:3]  # Cas, Per, etc.
        # RA: "00h 25m 17.4s" -> decimal hours
        ra_m = re.match(r"(\d+)h\s*(\d+)m\s*([\d.]+)s", ra_s.strip())
        if not ra_m:
            continue
        ra_h = int(ra_m.group(1)) + int(ra_m.group(2)) / 60.0 + float(ra_m.group(3)) / 3600.0
        # DEC: "+61º 19' 19"" or "-10º 37' 00"" (º or °, ' and " or ")
        dec_s_norm = dec_s.replace("\u00ba", " ").replace("\u00b0", " ").replace("'", " ").replace("\u201c", " ").replace("\u201d", " ").replace('"', " ")
        dec_m = re.match(r"([+-])?\s*(\d+)\s+(\d+)\s+(\d+)", dec_s_norm.strip())
        if not dec_m:
            continue
        sign = -1 if (dec_m.group(1) or "+") == "-" else 1
        dec_deg = sign * (int(dec_m.group(2)) + int(dec_m.group(3)) / 60.0 + int(dec_m.group(4)) / 3600.0)
        # Magnitude: "9.8v" -> 9.8 or None
        magn = None
        mag_clean = re.match(r"([\d.]+)", mag_s.strip())
        if mag_clean:
            try:
                magn = float(mag_clean.group(1))
            except ValueError:
                pass
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "OC", NULL, con, magn, NULL, NULL, catalog="Col"))
    return lines


def parse_melotte():
    """In-The-Sky Melotte catalogue (view=1). Save page(s) as melotte_p1.html, melotte_p2.html, melotte_p3.html.
    HTML table: <td>Mel N</td>...<td>HH<sup>h</sup>MM<sup>m</sup></td><td>&plus;DD&deg;MM&#39;</td>."""
    lines = []
    for fname in ["melotte.html", "melotte_p1.html", "melotte_p2.html", "melotte_p3.html"]:
        p = DL / fname
        if not p.exists():
            continue
        html = p.read_text(encoding="utf-8", errors="replace")
        # Match: >Mel N</a> (or </a>) then later (\d+)<sup>h</sup>(\d+)<sup>m</sup> and &plus; or &minus; (\d+)&deg;(\d+)&#39;
        for m in re.finditer(
            r">Mel\s+(\d+)<.*?(\d+)<sup>\s*h\s*</sup>(\d+)<sup>\s*m\s*</sup>.*?&(plus|minus);\s*(\d+)&deg;(\d+)&#39;",
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            mel_num, ra_hh, ra_mm, dec_sign, dec_dd, dec_mm = m.groups()
            name = f"Mel {mel_num}"
            ra_h = int(ra_hh) + int(ra_mm) / 60.0
            sign = -1 if dec_sign.lower() == "minus" else 1
            dec_deg = sign * (int(dec_dd) + int(dec_mm) / 60.0)
            lines.append(row(name, ra_h, dec_deg, NULL, NULL, "OC", NULL, NULL, NULL, NULL, NULL, catalog="Mel"))
    # Deduplicate by name (in case multiple pages have overlapping saves)
    seen = set()
    unique = []
    for r in lines:
        name = r.split("\t")[0]
        if name not in seen:
            seen.add(name)
            unique.append(r)
    return unique


def parse_barnard():
    """VII/220A: Barnard. barnard.dat bytes 2-5 Barn, 23-24 RA2000h, 26-27 RA2000m, 29-30 RA2000s, 33 DE2000-, 34-35 DE2000d, 37-38 DE2000m. J2000."""
    lines = []
    p = DL / "VII_220A_barnard.dat"
    if not p.exists():
        return lines
    for line in open(p):
        if len(line) < 39:
            continue
        try:
            barn = line[1:5].strip()
            if not barn:
                continue
            rah = int(line[22:24].strip() or 0)
            ram = int(line[25:27].strip() or 0)
            ras = int(line[28:30].strip() or 0)
            de_sign = line[32:33] or "+"
            ded = int(line[33:35].strip() or 0)
            dem = int(line[36:38].strip() or 0)
        except (ValueError, IndexError):
            continue
        ra_h = rah + ram / 60.0 + ras / 3600.0
        dec_deg = (1 if de_sign == "+" else -1) * (ded + dem / 60.0)
        name = f"B{barn}"
        lines.append(row(name, ra_h, dec_deg, NULL, NULL, "Dn", NULL, NULL, NULL, NULL, NULL, catalog="B"))
    return lines


def write_psql(shortname, title, descr, url, filename, parse_fn):
    """Write a catalog .psql file. COPY must include catalog column for FK."""
    lines = parse_fn()
    out = DL.parent / filename
    copy_cols = "name, ra, decl, descr, comment, type, epoch, const, magn, x, y, catalog"
    like_pattern = {"Ced": "Ced %", "vdB": "vdB %", "Sh2": "Sh2-%", "LBN": "LBN %", "LDN": "LDN %", "B": "B%", "Col": "Col %", "Mel": "Mel %"}[shortname]

    def esc(s):
        return (s or "").replace("'", "''")
    content = f"""--
-- {title}
--

DELETE FROM objects WHERE name LIKE '{like_pattern}';
DELETE FROM catalogs WHERE shortname='{shortname}';

INSERT INTO catalogs(shortname, name, filename, descr, url, version)
VALUES('{shortname}',
       '{esc(title)}',
       '{out.name}',
       '{esc(descr)}',
       '{esc(url)}',
       '1.0');

COPY objects ({copy_cols}) FROM stdin;
"""
    content += "\n".join(lines) + "\n\\.\n"
    out.write_text(content, encoding="utf-8")
    return len(lines)


def main():
    write_psql(
        "Ced",
        "Cederblad catalog of bright diffuse Galactic nebulae",
        "Catalog of bright diffuse Galactic nebulae (Cederblad 1946).",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/231",
        "catalog-cederblad.psql",
        parse_cederblad,
    )
    write_psql(
        "vdB",
        "van den Bergh catalogue of reflection nebulae",
        "Catalogue of reflection nebulae (van den Bergh 1966).",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/21",
        "catalog-vdb.psql",
        parse_vdb,
    )
    write_psql(
        "Sh2",
        "Sharpless catalogue of H II regions",
        "Catalogue of H II regions (Sharpless 1959). Sh2-NN designation.",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/20",
        "catalog-sharpless.psql",
        parse_sharpless,
    )
    write_psql(
        "LBN",
        "Lynds' Catalogue of Bright Nebulae",
        "Catalogue of bright nebulae (Lynds 1965).",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/9",
        "catalog-lbn.psql",
        parse_lbn,
    )
    write_psql(
        "LDN",
        "Lynds' Catalogue of Dark Nebulae",
        "Catalogue of dark nebulae (Lynds 1962, updated).",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/7A",
        "catalog-ldn.psql",
        parse_ldn,
    )
    write_psql(
        "B",
        "Barnard's Catalogue of Dark Objects",
        "Barnard's catalogue of 349 dark objects in the sky (1927).",
        "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=VII/220A",
        "catalog-barnard.psql",
        parse_barnard,
    )
    write_psql(
        "Col",
        "Collinder catalog of open star clusters (updated)",
        "Observer checklist from CloudyNights (Thomas Watson), updated coordinates from HCNGC.",
        "https://www.cloudynights.com/articles/articles/the-collinder-catalog-updated-r2467/",
        "catalog-collinder.psql",
        parse_collinder,
    )
    write_psql(
        "Mel",
        "Melotte catalogue of star clusters",
        "Catalogue of 245 star clusters (Melotte 1915). Data from In-The-Sky.org.",
        "https://in-the-sky.org/data/catalogue.php?cat=Melotte",
        "catalog-melotte.psql",
        parse_melotte,
    )
    print("Done. Run convert_catalogs.py to regenerate SQL from _dl/ data.")


if __name__ == "__main__":
    main()
