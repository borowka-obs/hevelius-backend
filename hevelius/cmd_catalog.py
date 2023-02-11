from hevelius import db
from hevelius.utils import parse_dec, parse_ra, format_dec, format_ra
from argparse import ArgumentTypeError
import sys


def format_get(format: str) -> str:
    """
    Ensures that the specified output format allowed. Allowed values are:
    - none - don't print frames list at all
    - filenames - print filenames only (useful for scripting)
    - csv - print all found frames in CSV format
    - brief - print a space separated list on the screen
    - full - print everything on the screen
    """
    if format not in ["none", "filenames", "csv", "brief", "full"]:
        raise ArgumentTypeError(f"unsupported format: {format}, allowed are: none, filenames, csv, brief, full")

    return format


def catalog(args):
    """
    Searches the objects catalog for objects close to specified coordinates.
    """

    ra = parse_ra(args.ra)
    decl = parse_dec(args.decl)
    radius = float(args.proximity)

    format = format_get(args.format)

    cnx = db.connect()

    if format != "csv":
        print(f"Looking for objects close to {format_ra(ra)},{format_dec(decl)}, within a radius of {radius} deg")

        objects = db.catalog_radius_get(cnx, ra, decl, radius)

        print(f"Found {len(objects)} object(s) that match criteria: distance from RA {format_ra(ra)} DEC {format_dec(decl)} no larger than {radius}")
        for object in objects:
            print(object)

    frames = db.tasks_radius_get(cnx, ra, decl, radius)

    if format != "csv":
        print(f"Found {len(frames)} frame(s) that match criteria: distance from RA {format_ra(ra)} DEC {format_dec(decl)} no larger than {radius}")
    cnx.close()

    if format == "none":
        return

    if format == "csv":
        print("# task_id, object, filename, fwhm, ra, decl, comment")
    # Print a space separated list of task IDs
    for frame in frames:
        if format == "filenames":
            print(frame[3])
        elif format == "brief":
            sys.stdout.write(f"{frame[0]} ")
        elif format == "full":
            print(f"Task {frame[0]}: RA {frame[4]} DEC {frame[5]}, object: {frame[1]}, file: {frame[2]}, fwhm: {frame[3]}")
        elif format == "csv":
            print(f"{frame[0]},{frame[1]},{frame[2]},{frame[3]},{frame[4]},{frame[5]},{frame[6]}")
    print("")
