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
