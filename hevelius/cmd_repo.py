"""
Code that handles files repository on disk.
"""
import glob

from os import listdir
from os.path import isfile, join
from pathlib import Path
from astropy.io import fits
import sys

from hevelius import config, db
from hevelius.iteleskop import parse_iteleskop_filename

def process_fits_list(fname, show_hdr: bool, dry_run: bool):
    """
    Processes all FITS files listed in a specified text file.

    :param fname: name of a text file that contains a list of files to be loaded
    :param show_hdr: bool governing whether FITS headers will be printed or not
    :param dry_run: bool governing if DB changes are to be done or not.
    """

    with open(fname) as f:
        lines = f.readlines()

    total = len(lines)
    print(f"Found {total} filename(s) in file {fname}")

    cnx = db.connect()

    cnt = 1
    for l in lines:
        l = l.strip()
        if len(l) == 0 or l[0] == "#":
            # Skip empty and commented out lines
            continue

        print(f"Processing file {cnt} of {total}: {l}")
        process_fits_file(cnx, l, show_hdr=show_hdr, dry_run=dry_run)
        cnt += 1

    cnx.close()


def process_fits_dir(dir: str, show_hdr: bool, dry_run: bool):
    """
    Processes all FITS files in specified directory.

    :param dir: directory to be traversed
    :param show_hdr: bool governing whether FITS headers will be printed or not
    :param dry_run: bool governing if DB changes are to be done or not.
    """

    files = []

    pattern = dir + '/' + '**' + '/' + '*.fit'
    print(f"pattern={pattern}")
    files = glob.glob(pattern, recursive=True)

    # for f in Path(dir).rglob('*.fit'):
    #    files.append(f)

    print(f"Found {len(files)} files(s) in directory {dir}")

    cnt = 1
    total = len(files)

    cnx = db.connect()

    for f in files:
        print(f"Processing file {cnt} of {total}: {f}")
        process_fits_file(cnx, str(f), show_hdr, dry_run)
        cnt += 1

    cnx.close()


def task_add(cnx, fname, details):
    """Adds a new task based on a image filename, specified by fname. The
       filename parsing is already done by parse_iteleskop_name() and stored in
       details dict."""

    user_id = db.user_get_id(cnx, aavso_id=details["user"])

    details["user_id"] = user_id
    details["scope_id"] = 1
    details["state"] = 6  # Complete

    # TODO: load fits, get its parameters. For example code, see cmd/parse-fits.py

    db.task_add(cnx, details)


def process_fits_file(cnx, fname, verbose=False, show_hdr=False, dry_run=False):
    """ Processes FITS file: reads its FITS content, then attempts to update the data in the database. """

    details = parse_iteleskop_filename(fname)
    if details:
        task_id = details["task_id"]
    else:
        task_id = 0

    if task_id == 0:
        print(f"ERROR: failed to parse file {fname}, skipping.")
        return

    if not db.task_exists(cnx, task_id):
        print(f"Task {task_id} does not exist, adding.")
        task_add(cnx, fname, details)
    else:
        print(f"Task {task_id} exists.")

    task_update_params(cnx, fname, task_id, verbose=verbose, dry_run=dry_run)

def task_update_params(cnx, fname: str, task_id: int, verbose=False, dry_run=False):

    h = read_fits(fname)

    if verbose:
        print(f"Header file: {repr(h)}")

    q = "UPDATE tasks SET "

    q += get_int_header(h, "he_resx", "NAXIS1")
    q += get_int_header(h, "he_resy", "NAXIS2")

    q += "he_obsstart='%s', " % gets(h, "DATE-OBS")
    q += "he_exposure=%f, " % getf(h, "EXPTIME")

    q += get_float_header(h, "he_settemp", "SET-TEMP")
    q += get_float_header(h, "he_ccdtemp", "CCD-TEMP")

    q += "he_pixwidth=%f, " % getf(h, "XPIXSZ")
    q += "he_pixheight=%f, " % getf(h, "YPIXSZ")
    q += "he_xbinning=%d, " % geti(h, "XBINNING")
    q += "he_ybinning=%d, " % geti(h, "YBINNING")
    q += "he_filter='%s', " % gets(h, "FILTER")

    if "OBJCTRA" in h:
        q += "he_objectra=%f, " % parse_ra(gets(h, "OBJCTRA"))
        q += "he_objectdec=%f, " % parse_dec(gets(h, "OBJCTDEC"))

    q += get_float_header(h, "he_objectalt", "OBJCTALT")
    q += get_float_header(h, "he_objectaz", "OBJCTAZ")
    q += get_float_header(h, "he_objectha", "OBJCTHA")
    q += get_string_header(h, "he_pierside", "PIERSIDE")

    q += "he_site_lat=%f, " % parse_degms(gets(h, "SITELAT"))
    q += "he_site_lon=%f, " % parse_degms(gets(h, "SITELONG"))

    q += "he_jd=%f, " % getf(h, "JD")

    q += get_float_header(h, "he_jd_helio", "JD-HELIO")

    q += get_float_header(h, "he_tracktime", "TRAKTIME")

    q += "he_focal=%f, " % getf(h, "FOCALLEN")
    q += "he_aperture_diam=%f, " % getf(h, "APTDIA")
    q += "he_aperture_area=%f, " % getf(h, "APTAREA")
    q += "he_scope='%s', " % gets(h, "TELESCOP")
    q += "he_camera='%s', " % gets(h, "INSTRUME")

    q += get_float_header(h, "he_moon_alt", "MOONWYS")
    q += get_float_header(h, "he_moon_angle", "MOONKAT")
    q += get_float_header(h, "he_moon_phase", "MOONFAZA")
    q += get_float_header(h, "he_sun_alt", "SUN")
    # sets he_solved, he_solved_ra, he_solved_dec, he_solved_x, he_solved_y
    q += parse_solved(h)

    q += parse_quality(h)  # gets FWHM, number of stars recognized

    # meaningless, but it's hard to tell if q ends with a , or not at this point.
    q += " task_id=task_id"

    q += f" WHERE task_id={task_id};"

    if verbose:
        print(q, file=sys.stderr)

    if not dry_run:
        v = db.run_query(cnx, q)
        print(f"Task {task_id} updated.")

    else:
        print(f"Task {task_id} update skipped (--dry-run).")


def get_int_header(header, sql, header_name):
    if not header_name in header or not len(str(header[header_name])):
        return ""
    return "%s=%i, " % (sql, geti(header, header_name))


def get_float_header(header, sql, header_name):
    if not header_name in header or not len(str(header[header_name])):
        return ""
    return "%s=%f, " % (sql, getf(header, header_name))


def get_string_header(header, sql, header_name):
    if not header_name in header or not len(str(header[header_name])):
        return ""
    return "%s='%s', " % (sql, gets(header, header_name))


def parse_ra(s):
    """ Converts '18 18 49.00'' into 18.123456 """
    dms = s.split(" ")

    ra = float(dms[0])

    minus = ra < 0
    ra = abs(ra)

    ra += float(dms[1])/60.0 + float(dms[2])/3600.0

    return ra*(1-2*minus)


def parse_dec(s):
    return parse_ra(s)


def parse_degms(s):
    return parse_ra(s)


def parse_solved(h):

    # Here's example FITS header this code is supposed to parse.
    # PA      =   6.40789182622E+001 / [deg, 0-360 CCW] Position angle of plate
    # CTYPE1  = 'RA---TAN'           / X-axis coordinate type
    # CRVAL1  =   2.74719564502E+002 / X-axis coordinate value
    # CRPIX1  =   2.04800000000E+003 / X-axis reference pixel
    # CDELT1  =  -1.77681403340E-004 / [deg/pixel] X-axis plate scale
    # CROTA1  =  -6.40789182622E+001 / [deg] Roll angle wrt X-axis
    # CTYPE2  = 'DEC--TAN'           / Y-axis coordinate type
    # CRVAL2  =  -1.37998534456E+001 / Y-axis coordinate value
    # CRPIX2  =   2.04800000000E+003 / Y-axis reference pixel
    # CDELT2  =  -1.77675999978E-004 / [deg/pixel] Y-Axis Plate scale
    # CROTA2  =  -6.40789182622E+001 / [deg] Roll angle wrt Y-axis
    # CD1_1   =  -7.76703599758E-005 / Change in RA---TAN along X-Axis
    # CD1_2   =  -1.59801261123E-004 / Change in RA---TAN along Y-Axis
    # CD2_1   =   1.59806120891E-004 / Change in DEC--TAN along X-Axis
    # CD2_2   =  -7.76679979895E-005 / Change in DEC--TAN along Y-Axis

    if not "PLTSOLVD" in h:
        return "he_solved=0, "

    solved = h["PLTSOLVD"]
    if solved != True:
        return "he_solved=0, "

    # Ok, the header claims it's solved. Let's try to find it out
    q = "he_solved=1, "

    # Let's check if the first parameter is RA
    if not h["CTYPE1"] or h["CTYPE1"] != 'RA---TAN':
        print("Can't parse solved RA.")
        return "he_solved=2, "

    ra = float(h["CRVAL1"])

    # Now check declination
    if not h["CTYPE2"] or h["CTYPE2"] != 'DEC--TAN':
        print("Can't parse solved DEC.")
        return "he_solved=2, "

    dec = float(h["CRVAL2"])

    # Ok, now parse the x-axis reference pixel
    refx = int(h["CRPIX1"])
    refy = int(h["CRPIX2"])

    pixscalex = float(h["CDELT1"])*3600  # arcsec/pix in x direction
    pixscaley = float(h["CDELT2"])*3600  # arcsec/pix in y direction

    q += "he_solved_ra=%f, he_solved_dec=%f, he_solved_refx=%d, he_solved_refy=%d, he_pixscalex=%f, he_pixscaley=%f, " \
         % (ra, dec, refx, refy, pixscalex, pixscaley)

    # CD1_1   =  -7.76703599758E-005 / Change in RA---TAN along X-Axis
    # CD1_2   =  -1.59801261123E-004 / Change in RA---TAN along Y-Axis
    # CD2_1   =   1.59806120891E-004 / Change in DEC--TAN along X-Axis
    # CD2_2   =  -7.76679979895E-005 / Change in DEC--TAN along Y-Axis
    ra_change_x = float(h["CD1_1"])
    ra_change_y = float(h["CD1_2"])
    dec_change_x = float(h["CD2_1"])
    dec_change_y = float(h["CD2_2"])

    q += "he_solved_ra_change_x=%f, he_solved_ra_change_y=%f, he_solved_dec_change_x=%f, he_solved_dec_change_y=%f, " \
        % (ra_change_x, ra_change_y, dec_change_x, dec_change_y)

    return q


def parse_quality(header):

    q = ""
    if "FWHM" in header:
        q = "he_fwhm=%f, " % getf(header, "FWHM")

    if not "HISTORY" in header:
        return q

    for h in header["HISTORY"]:
        # There may be many HISTORY entries. We're looking for the one looking like this:
        # Matched 139 stars from the USNO UCAC4 Catalog
        if h.find("Matched ") == -1 or h.find("stars from the") == -1:
            continue

        h = h.strip()
        x = h.split(" ")
        stars = int(x[1])
        q += "he_stars=%d, " % stars
        break

    return q


def gets(header, param):
    return header[param]


def getf(header, param):
    return float(header[param])


def geti(header, param):
    return int(header[param])


def read_fits(filename):
    """ Reads FITS file, returns its header content """

    hdul = fits.open(filename)

    return hdul[0].header


def repo(args):
    """Manages the on disk images repository."""

    if args.file:
        cnx = None
        if not args.dry_run:
            cnx = db.connect()
        print(f"Processing single file: {args.file}")
        process_fits_file(cnx, args.file, show_hdr=args.show_header, dry_run=args.dry_run)
        if cnx:
            cnx.close()
    elif args.list:
        print(f"Processing list of files stored in {args.list}")
        process_fits_list(args.list, show_hdr=args.show_header,dry_run=args.dry_run)
    else:
        if args.dir:
            path = args.dir
        else:
            path = config.REPO_PATH

        print(f"Processing all *.fit files in dir: {path}")
        pattern = config.REPO_PATH + '/' + '**' + '/' + '*.fit'

        process_fits_dir(path, show_hdr=args.show_header, dry_run=args.dry_run)
