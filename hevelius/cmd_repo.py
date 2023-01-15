from hevelius import config, db
import glob
import re
import os


def parse_iteleskop_filename(fname):

    # Step 1: get rid of the possible leading dir name.
    dir, filename = os.path.split(fname)  # get rid of the directory
    filename, _ = os.path.splitext(filename) # and the extension

    regex = '([S_][F_][D_][B_])_([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})_J([0-9]+)_([A-Z]+)_([A-Z0-9]+)_([0-9]x[0-9])_([0-9]+)s_(.*)'
    m = re.match(regex, filename)
    if m:
        flags, date, task_id, user,filter, bin, exp, object = m.groups()
        bin = int(bin[0])

        solved = (flags[0] == 'S')
        calibrated = (flags[1:4] == "FDB")

        # print(f"Parsed flags={flags} date={date} task_id={task_id} user={user} filter={filter} bin={bin} exp={exp} object={object}")
        return {
            "flags": flags,
            "date": date,
            "task_id": int(task_id),
            "user": user,
            "filter": filter,
            "binning": int(bin),
            "exposure": exp,
            "object": object,
            "imagename": fname,
            "solve": solved,
            "solved": solved,
            "calibrate": calibrated,
            "calibrated": calibrated
        }
    else:
        return None

def task_add(cnx, fname, details):
    """Adds a new task based on a image filename, specified by fname. The
       filename parsing is already done by parse_iteleskop_name() and stored in
       details dict."""

    user_id = db.user_get_id(cnx, aavso_id = details["user"])
    print(f"#### user_id={user_id}")

    details["user_id"] = user_id
    details["scope_id"] = 1
    details["state"] = 6 # Complete

    print(details)

    db.task_add(cnx, details)


def process_file(fname, cnt, total):

    fname = fname.replace(config.REPO_PATH + "/", "")
    print(f"Processing {cnt}/{total}: {fname}")
    details = parse_iteleskop_filename(fname)

    if details:
        cnx = db.connect()
        task_id = details["task_id"]
        if db.task_exists(cnx, task_id):
            print(f"Task {task_id} exists.")
        else:
            print(f"Task {task_id} does not exist.")

            task_add(cnx, fname, details)

        cnx.close()

def repo(args):
    """Manages the on disk images repository."""

    print(f"Repository path: {config.REPO_PATH}")

    # You can specify dirs to skip when searching for files.
    dir_to_exclude = ['B', 'C']

    pattern = config.REPO_PATH + '/' + '**' + '/' + '*.fit'

    print(f"pattern={pattern}")
    files = glob.glob(pattern, recursive=True)

    total = len(files)

    print(f"{total} file(s) found in {config.REPO_PATH}")

    cnt = 1
    for f in files:
        process_file(f, cnt, total)
        cnt += 1
