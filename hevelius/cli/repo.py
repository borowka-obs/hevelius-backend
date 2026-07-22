"""
Code that handles files repository on disk.
"""
import glob
import sys
from astropy.io import fits
import os

from hevelius import config, db
from hevelius.iteleskop import parse_iteleskop_filename


def process_fits_list(fname, show_hdr: bool, dry_run: bool):
    """
    Processes all FITS files listed in a specified text file.

    :param fname: name of a text file that contains a list of files to be loaded
    :param show_hdr: bool governing whether FITS headers will be printed or not
    :param dry_run: bool governing if DB changes are to be done or not.
    """

    with open(fname, encoding="utf-8") as f:
        lines = f.readlines()

    total = len(lines)
    print(f"Found {total} filename(s) in file {fname}")

    cnx = db.connect()

    cnt = 1
    for line in lines:
        line = line.strip()
        if len(line) == 0 or line[0] == "#":
            # Skip empty and commented out lines
            continue

        print(f"Processing file {cnt} of {total}: {line}")
        process_fits_file(cnx, line, show_hdr=show_hdr, dry_run=dry_run)
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

    query = "UPDATE tasks SET "

    query += get_int_header(h, "he_resx", "NAXIS1")
    query += get_int_header(h, "he_resy", "NAXIS2")

    query += f"he_obsstart='{gets(h, 'DATE-OBS')}', "
    query += f"he_exposure={getf(h, 'EXPTIME')}, "

    query += get_float_header(h, "he_settemp", "SET-TEMP")
    query += get_float_header(h, "he_ccdtemp", "CCD-TEMP")

    query += f"he_pixwidth={getf(h, 'XPIXSZ')}, "
    query += f"he_pixheight={getf(h, 'YPIXSZ')}, "
    query += f"he_xbinning={geti(h, 'XBINNING')}, "
    query += f"he_ybinning={geti(h, 'YBINNING')}, "
    query += f"he_filter='{gets(h, 'FILTER')}', "

    if "OBJCTRA" in h:
        query += f"he_objectra={parse_ra(gets(h, 'OBJCTRA'))}, "
        query += f"he_objectdec={parse_dec(gets(h, 'OBJCTDEC'))}, "

    query += get_float_header(h, "he_objectalt", "OBJCTALT")
    query += get_float_header(h, "he_objectaz", "OBJCTAZ")
    query += get_float_header(h, "he_objectha", "OBJCTHA")
    query += get_string_header(h, "he_pierside", "PIERSIDE")

    query += f"he_site_lat={parse_degms(gets(h, 'SITELAT'))}, "
    query += f"he_site_lon={parse_degms(gets(h, 'SITELONG'))}, "

    query += f"he_jd={getf(h, 'JD')}, "

    query += get_float_header(h, "he_jd_helio", "JD-HELIO")

    query += get_float_header(h, "he_tracktime", "TRAKTIME")

    query += f"he_focal={getf(h, 'FOCALLEN')}, "
    query += f"he_aperture_diam={getf(h, 'APTDIA')}, "
    query += f"he_aperture_area={getf(h, 'APTAREA')}, "
    query += f"he_scope='{gets(h, 'TELESCOP')}', "
    query += f"he_camera='{gets(h, 'INSTRUME')}', "

    query += get_float_header(h, "he_moon_alt", 'MOONWYS')
    query += get_float_header(h, "he_moon_angle", 'MOONKAT')
    query += get_float_header(h, "he_moon_phase", 'MOONFAZA')
    query += get_float_header(h, "he_sun_alt", 'SUN')
    # sets he_solved, he_solved_ra, he_solved_dec, he_solved_x, he_solved_y
    query += parse_solved(h)

    query += parse_quality(h)  # gets FWHM, number of stars recognized

    # meaningless, but it's hard to tell if q ends with a , or not at this point.
    query += " task_id=task_id"

    query += f" WHERE task_id={task_id};"

    if verbose:
        print(query, file=sys.stderr)

    if not dry_run:
        v = db.run_query(cnx, query)
        print(f"Task {task_id} updated, result: {v}.")

    else:
        print(f"Task {task_id} update skipped (--dry-run).")


def get_int_header(header, sql, header_name):
    """
    Returns specified integer field from the header
    """
    if header_name not in header or not len(str(header[header_name])):
        return ""
    return "%s=%i, " % (sql, geti(header, header_name))


def get_float_header(header, sql, header_name):
    """
    Returns specified float field from the header
    """
    if header_name not in header or not len(str(header[header_name])):
        return ""
    return "%s=%f, " % (sql, getf(header, header_name))


def get_string_header(header, sql, header_name):
    """
    Returns specified string field from the header
    """
    if header_name not in header or not len(str(header[header_name])):
        return ""
    return "%s='%s', " % (sql, gets(header, header_name))


def parse_ra(s):
    """ Converts Right Ascension from one format to another: '18 18 49.00'' into 18.123456 """
    dms = s.split(" ")

    ra = float(dms[0])

    minus = ra < 0
    ra = abs(ra)

    ra += float(dms[1]) / 60.0 + float(dms[2]) / 3600.0

    return ra * (1 - 2 * minus)


def parse_dec(s):
    """
    Parse declination.
    """
    return parse_ra(s)


def parse_degms(s):
    """
    Parse degrees/minutes/seconds
    """
    return parse_ra(s)


def parse_solved(h):
    """
    Returns string formatting that specifies if the frame was solved or not.
    """

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

    if "PLTSOLVD" not in h:
        return "he_solved=0, "

    solved = h["PLTSOLVD"]
    if not solved:
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

    pixscalex = float(h["CDELT1"]) * 3600  # arcsec/pix in x direction
    pixscaley = float(h["CDELT2"]) * 3600  # arcsec/pix in y direction

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
        q = f"he_fwhm={getf(header, 'FWHM')}, "

    if "HISTORY" not in header:
        return q

    for h in header["HISTORY"]:
        # There may be many HISTORY entries. We're looking for the one looking like this:
        # Matched 139 stars from the USNO UCAC4 Catalog
        if h.find("Matched ") == -1 or h.find("stars from the") == -1:
            continue

        h = h.strip()
        x = h.split(" ")
        stars = int(x[1])
        q += f"he_stars={stars}, "
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


def sanity_files(args):
    """This goes through the list of files and check if related tasks are present (and updates them if needed)"""

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
        process_fits_list(args.list, show_hdr=args.show_header, dry_run=args.dry_run)
    else:
        if args.dir:
            path = args.dir
        else:
            path = config.load_config()['paths']['repo-path']

        print(f"Processing all *.fit files in dir: {path}")
        process_fits_dir(path, show_hdr=args.show_header, dry_run=args.dry_run)


def sanity_db(args):
    """This goes through the list of tasks and check if related files are present (and flags tasks that have missing files)"""

    # Get configuration for repository path
    config_data = config.load_config()
    repo_path = config_data['paths']['repo-path']

    # Parse min/max task_id range if specified
    min_task_id = getattr(args, 'min_task_id', None)
    max_task_id = getattr(args, 'max_task_id', None)

    # Check if we should delete invalid tasks
    delete_invalid = getattr(args, 'delete_invalid', False)

    print(f"Checking database sanity against repository path: {repo_path}")
    if min_task_id is not None or max_task_id is not None:
        print(f"Task ID range: {min_task_id or 'all'} to {max_task_id or 'all'}")
    print(f"Delete invalid tasks: {delete_invalid}")
    print()

    # Connect to database
    cnx = db.connect()

    # Build query to get tasks
    query = "SELECT task_id, imagename FROM tasks"
    conditions = []

    if min_task_id is not None:
        conditions.append(f"task_id >= {min_task_id}")
    if max_task_id is not None:
        conditions.append(f"task_id <= {max_task_id}")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY task_id"

    # Execute query
    tasks = db.run_query(cnx, query)

    if not tasks:
        print("No tasks found in the specified range.")
        cnx.close()
        return

    print(f"Found {len(tasks)} tasks to check.")
    print()

    # Track issues
    tasks_no_filename = []
    tasks_missing_file = []
    tasks_ok = []

    # Check each task
    for task in tasks:
        task_id = task[0]
        imagename = task[1]

        if not imagename:
            # Task has no filename specified
            tasks_no_filename.append(task_id)
            continue

        # Check if file exists on disk
        file_path = os.path.join(repo_path, imagename)
        if os.path.exists(file_path):
            tasks_ok.append(task_id)
        else:
            # Task has filename but file is missing
            tasks_missing_file.append(task_id)

    # Print results
    print("=== SANITY CHECK RESULTS ===")
    print()

    if tasks_no_filename:
        print(f"Tasks with NO filename specified ({len(tasks_no_filename)}):")
        for task_id in tasks_no_filename:
            print(f"  Task {task_id}")
        print()
    else:
        print("✓ All tasks have filenames specified.")
        print()

    if tasks_missing_file:
        print(f"Tasks with MISSING files on disk ({len(tasks_missing_file)}):")
        for task_id in tasks_missing_file:
            # Get the filename for display
            task_info = db.run_query(cnx, f"SELECT imagename FROM tasks WHERE task_id = {task_id}")
            if task_info:
                filename = task_info[0][0]
                print(f"  Task {task_id}: {filename}")
        print()
    else:
        print("✓ All files referenced by tasks exist on disk.")
        print()

    print(f"Tasks OK: {len(tasks_ok)}")
    print(f"Total issues: {len(tasks_no_filename) + len(tasks_missing_file)}")
    print()

    # Handle deletion if requested
    if delete_invalid and (tasks_no_filename or tasks_missing_file):
        invalid_tasks = tasks_no_filename + tasks_missing_file

        if not getattr(args, 'dry_run', False):
            print(f"Deleting {len(invalid_tasks)} invalid tasks...")

            # Delete tasks in batches to avoid long-running transactions
            batch_size = 100
            for i in range(0, len(invalid_tasks), batch_size):
                batch = invalid_tasks[i:i + batch_size]
                task_ids_str = ','.join(map(str, batch))

                delete_query = f"DELETE FROM tasks WHERE task_id IN ({task_ids_str})"
                result = db.run_query(cnx, delete_query)

                print(f"  Deleted batch {i//batch_size + 1}: {len(batch)} tasks, status: {result}")

            print("Invalid tasks deleted successfully.")
        else:
            print(f"DRY RUN: Would delete {len(invalid_tasks)} invalid tasks.")
            print("Use --delete-invalid without --dry-run to actually delete them.")

    elif delete_invalid:
        print("No invalid tasks to delete.")

    cnx.close()


def repo(args):
    """Manages the on disk images repository."""

    if args.sanity_files:
        sanity_files(args)

    if args.sanity_db:
        sanity_db(args)

    if not args.sanity_files and not args.sanity_db:
        print("ERROR: No sanity check selected. Use --sanity-files or --sanity-db to check the repository.")
        return -1
