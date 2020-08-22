

import mysql.connector
from hevelius import config

def connect():
    cnx = mysql.connector.connect(user=config.USER, password=config.PASSWORD, database=config.DBNAME, host=config.HOST, port=config.PORT)
    return cnx

def run_query(cnx, query):
    cursor = cnx.cursor() # cursor(dictionary=True) or cursor(named_tuple=True)
    cursor.execute(query)
    try:
        result = cursor.fetchall()
    except:
        result = None # If this is an update or delete query.
        cnx.commit()
    cursor.close()
    return result

def version_get(cnx):
    query = 'SELECT * from schema_version'
    cursor = cnx.cursor()
    cursor.execute(query)

    for i in cursor:
        ver = i[0]

    cursor.close()
    return ver

def stats_get(cnx):

    # Get overall tasks counters
    tasks_cnt = run_query(cnx, 'SELECT count(*) from tasks')
    files_cnt = run_query(cnx, 'SELECT count(*) from tasks where imagename is not null')

    return tasks_cnt[0][0], files_cnt[0][0]

def stats_by_state(cnx):
    # Get tasks list by status
    hist = run_query(cnx, 'SELECT state, count(*) from tasks group by state')
    res = []

    for row in hist:
        res.append( (row[0], row[1]))

    return res

def stats_by_user(cnx, state = 6):
    if state is None:
        cond = ""
    else:
        cond = "WHERE state == %d" % state

    q = "SELECT login, tasks.user_id, count(*) from tasks, users where tasks.user_id = users.user_id %s group by tasks.user_id" % cond

    tasks_per_user = run_query(cnx, q)

    return tasks_per_user

def task_get(cnx, id):
    q = "SELECT task_id, state, user_id, imagename, object, descr, comment, ra, decl, exposure, filter, binning, guiding, fwhm, eccentricity FROM tasks WHERE task_id = %d" % id

    t = run_query(cnx, q)[0]

    x = {}
    x["id"] = t[0]
    x["state"] = t[1]
    x["user_id"] = t[2]
    x["file"] = t[3]
    x["object"] = t[4]
    x["descr"] = t[5]
    x["comment"] = t[6]
    x["ra"] = t[7]
    x["decl"] = t[8]
    x["exposure"] = t[9]
    x["filter"] = t[10]
    x["binning"] = t[11]
    x["guiding"] = t[12]
    x["fwhm"] = t[13]
    x["eccentricity"] = t[14]

    return x

def task_update(cnx, id, fwhm = None, eccentricity = None):
    upd = ""
    if fwhm is not None:
        upd = "fwhm = %f" % fwhm
    if eccentricity is not None:
        if len(upd):
            upd += ", "
        upd += "eccentricity = %f" % eccentricity
    
    if not len(upd):
        print("Nothing to update in task %d, aborting" % id)

    q = "UPDATE tasks SET %s WHERE task_id=%d" % (upd, id)

    print("Updating task %d: query=[%s]" % (id, q))

    run_query(cnx, q)
        