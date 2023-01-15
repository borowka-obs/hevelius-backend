import sys
import re
import os

def filename_to_task_id(fname):
    # Get rid of the paths first.
    tmp = fname[fname.rfind("/") + 1:]

    # then, get the J012345 substring, which designates the task id.
    try:
        offset = tmp.find("J") + 1
        tmp2 = tmp[offset:offset+6]
        return int(tmp2)
    except ValueError:
        print("ERROR: Unable to parse task id from [%s], tmp=[%s] tmp2=[%s]" % (fname, tmp, tmp2), file = sys.stderr)
        return -1

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
