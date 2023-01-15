from hevelius import config, db
from hevelius.iteleskop import parse_iteleskop_filename
import glob

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

    # TODO: load fits, get its parameters. For example code, see cmd/parse-fits.py

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
