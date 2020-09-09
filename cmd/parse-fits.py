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

    print(repr(h))

    task_id = iteleskop.filename_to_task_id(fname)

    q = "UPDATE tasks SET "

    q += "he_resx=%s, " % geth(h, "NAXIS1")
    q += "he_resy=%s, " % geth(h, "NAXIS2")

    q += " WHERE task_id=%d" % task_id

    print(q)



    cnx = db.connect()

    v = db.version_get(cnx)

    print("Schema version is %d" % v)

    if (v == 0):
        print("Schema version is 0, can't show any stats")
        return

    return

    stats = db.stats_get(cnx)
    print("There are %d tasks, %d files, %d have FWHM, %d have eccentricity." % stats)
    print("Missing: %d files miss FWHM, %d files miss eccentricity." % (stats[1] - stats[2], stats[1] - stats[3]))

    print("Stats by state:")
    by_state = db.stats_by_state(cnx)
    for id,name,cnt in by_state:
        print("%18s(%2d): %d" % (name, id, cnt))

    cnx.close()

def geth(header, param):
    return header[param]


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
