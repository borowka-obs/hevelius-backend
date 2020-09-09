#!/usr/bin/env python3

from os import listdir
from os.path import isfile, join
from astropy.io import fits
import sys
import subprocess
import argparse

# This is an ugly hack. It should be removed.
sys.path.append(".")
from hevelius import db
from hevelius import config
from hevelius import iteleskop

def process_fits_file(fname):
    """ Processes FITS file: reads its FITS content, then attempts to update the data in the database. """

    h = read_fits(fname)

    # Uncomment for nice FITS header print
    #print(repr(h))

    task_id = iteleskop.filename_to_task_id(fname)

    q = "UPDATE tasks SET "

    q += "he_resx=%d, " % geti(h, "NAXIS1")
    q += "he_resy=%d, " % geti(h, "NAXIS2")
    q += "he_obsstart='%s', " % gets(h, "DATE-OBS")
    q += "he_exposure=%f, " % getf(h, "EXPTIME")
    q += "he_settemp=%f, " % getf(h, "SET-TEMP")
    q += "he_ccdtemp=%f, " % getf(h, "CCD-TEMP")
    q += "he_pixwidth=%f, " % getf(h, "XPIXSZ")
    q += "he_pixheight=%f, " % getf(h, "YPIXSZ")
    q += "he_xbinning=%d, " % geti(h, "XBINNING")
    q += "he_ybinning=%d, " % geti(h, "YBINNING")
    q += "he_filter='%s', " % gets(h, "FILTER")

    q += "he_objectra=%f, " % parse_ra(gets(h, "OBJCTRA"))
    q += "he_objectdec=%f, " % parse_dec(gets(h, "OBJCTDEC"))
    q += "he_objectalt=%f, " % getf(h,"OBJCTALT")
    q += "he_objectaz=%f, " % getf(h,"OBJCTAZ")
    q += "he_objectha=%f, " % getf(h,"OBJCTHA")
    q += "he_pierside='%s', " % gets(h,"PIERSIDE")

    q += "he_site_lat=%f, " % parse_degms(gets(h,"SITELAT"))
    q += "he_site_lon=%f, " % parse_degms(gets(h,"SITELONG"))

    q += "he_jd=%f, " % getf(h,"JD")
    q += "he_jd_helio=%f, " % getf(h,"JD-HELIO")
    q += "he_tracktime=%f, " % getf(h,"TRAKTIME")

    q += "he_focal=%f, " % getf(h,"FOCALLEN")
    q += "he_aperture_diam=%f, " % getf(h,"APTDIA")
    q += "he_aperture_area=%f, " % getf(h,"APTAREA")
    q += "he_scope='%s', " % gets(h,"TELESCOP")
    q += "he_camera='%s', " % gets(h,"INSTRUME")

    q += "he_moon_alt=%f, " % getf(h,"MOONWYS")
    q += "he_moon_angle=%f, " % getf(h,"MOONKAT")
    q += "he_moon_phase=%f, " % getf(h,"MOONFAZA")
    q += "he_sun_alt=%f, " % getf(h,"SUN")
    q += parse_solved(h) # sets he_solved, he_solved_ra, he_solved_dec, he_solved_x, he_solved_y

    q += parse_quality(h) # gets FWHM, number of stars recognized

    q += " WHERE task_id=%d" % task_id

    print(q)

    cnx = db.connect()

    v = db.run_query(cnx, q)
    cnx.close()

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

    pixscalex = float(h["CDELT1"])*3600 # arcsec/pix in x direction
    pixscaley = float(h["CDELT2"])*3600 # arcsec/pix in y direction

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

    q += "he_solved_ra_change_x=%f, he_solved_ra_change_y=%f, he_solved_dec_change_x=%f, he_solved_dec_change_y=%f" \
        % (ra_change_x, ra_change_y, dec_change_x, dec_change_y)

    return q

def parse_quality(header):

    q = ", he_fwhm=%f" % getf(header,"FWHM")

    for h in header["HISTORY"]:
        # There may be many HISTORY entries. We're looking for the one looking like this:
        # Matched 139 stars from the USNO UCAC4 Catalog
        if h.find("Matched ") == -1 or h.find("stars from the") == -1:
            continue

        h = h.strip()
        x = h.split(" ")
        print(x)
        stars = int(x[1])
        q += ", he_stars=%d" % stars
        break

    return q

def gets(header, param):
    return header[param]

def getf(header, param):
    return float(header[param])

def geti(header, param):
    return int(header[param])

def process_fits_list(fname):
    """ Processes a file that contains a list of FITS files. """
    raise NotImplementedError("not implemented")

def read_fits(filename):
    """ Reads FITS file, returns its header content """

    hdul = fits.open(filename)

    return hdul[0].header


if __name__ == '__main__':
    print("Hevelius db-migrate 0.1")

    parser = argparse.ArgumentParser("Hevelius FITS parser 0.1.0")

    file_parser = parser.add_argument('-f', "--file", help="Reads a single FITS file", type=str)
    list_parser = parser.add_argument("-l", "--list", help="Reads a list of FITS files (one filename per line)", type=str)

    args = parser.parse_args()

    if args.file:
        process_fits_file(args.file)
    if args.list:
        process_fits_list(args.list)
