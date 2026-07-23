"""CLI: search tasks/frames near sky coordinates."""
from argparse import ArgumentTypeError
import sys

from hevelius import db
from hevelius.config import load_config
from hevelius.utils import format_dec, format_ra, parse_dec, parse_ra


def format_get(format: str) -> str:
    """
    Ensures that the specified output format allowed. Allowed values are:
    - none - don't print frames list at all
    - filenames - print filenames only (useful for scripting)
    - csv - print all found frames in CSV format
    - brief - print a space separated list on the screen
    - full - print everything on the screen
    - pixinsight - print a list of frames in PixInsight format (useful for
                    importing into SubframeSelector)
    """
    if format not in ["none", "filenames", "csv", "brief", "full", "pixinsight"]:
        raise ArgumentTypeError(
            f"unsupported format: {format}, allowed are: none, filenames, csv, brief, full, pixinsight"
        )

    return format


def task_search(args):
    """
    Search for frames (completed tasks) near specified coordinates.

    Coordinates come from --object (catalog name lookup) or --ra/--decl.
    """

    conn = db.connect()

    if len(args.object):
        print(f"Looking for object {args.object}")
        obj = db.catalog_get(conn, args.object)
        if obj != []:
            ra = obj[0][3]
            decl = obj[0][4]
            print(
                f"Found object {args.object} in a catalog, using its coords: "
                f"RA {format_ra(ra)} DEC {format_dec(decl)}"
            )
        else:
            print(f"Object {args.object} not found in a catalog")
            conn.close()
            return 1
    else:
        ra = parse_ra(args.ra)
        decl = parse_dec(args.decl)

    radius = float(args.proximity)
    out_format = format_get(args.format)

    filter_sql = ""
    if args.bin:
        filter_sql = f" AND binning={args.bin}"
    if args.focal:
        filter_sql += f" AND he_focal={args.focal}"
    if args.resx:
        filter_sql += f" AND he_resx={args.resx}"
    if args.resy:
        filter_sql += f" AND he_resy={args.resy}"

    sensor_id = 0
    if args.sensor != "":
        sensor = db.sensor_get_by_name(conn, args.sensor)
        if sensor == []:
            print(f"Sensor {args.sensor} not found in the database")
            conn.close()
            return 1
        sensor_id = sensor[0]
        print(f"Found sensor id ({sensor_id}): " + str(sensor))

    if args.sensor_id != 0:
        sensor_id = args.sensor_id

    if sensor_id != 0:
        filter_sql += f" AND sensor_id={sensor_id}"

    frames = db.tasks_radius_get(
        conn, ra, decl, radius, filter=filter_sql, order="he_fwhm ASC"
    )

    print(
        f"Found {len(frames)} frame(s) that match criteria: distance from "
        f"RA {format_ra(ra)} DEC {format_dec(decl)} no larger than {radius},"
        f" binning={args.bin}, focal={args.focal}, resx={args.resx}, resy={args.resy}"
    )
    conn.close()

    if out_format == "none":
        return 0

    repo_path = load_config()['paths']['repo-path']

    if out_format == "csv":
        print(
            "# task_id, object, filename, fwhm, ra, decl, comment, "
            "he_resx, he_resy, filter, he_focal, binning"
        )
    for frame in frames:
        if out_format == "filenames":
            print(frame[2])
        elif out_format == "brief":
            sys.stdout.write(f"{frame[0]} ")
        elif out_format == "full":
            print(
                f"Task {frame[0]}: RA {frame[4]} DEC {frame[5]}, "
                f"object: {frame[1]}, file: {frame[2]}, fwhm: {frame[3]}"
            )
        elif out_format == "csv":
            print(
                f"{frame[0]},{frame[1]},{frame[2]},{frame[3]},{frame[4]},{frame[5]},"
                f"{frame[6]},{frame[7]},{frame[8]},{frame[9]},{frame[10]}, {frame[11]}"
            )
        elif out_format == "pixinsight":
            print(f'   [true, "{repo_path}/{frame[2]}", "", ""],')
    print("")
    return 0
