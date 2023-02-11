
import numpy as np
import pandas as pd
import plotly.express as px

from hevelius import db
from hevelius.utils import deg2rah


def stats():
    """
    Prints database statistics (version, overall, by state, by user)

    :param args: arguments parsed by argparse
    """

    cnx = db.connect()

    ver = db.version_get(cnx)

    print(f"Schema version is {ver}")

    if ver == 0:
        print("DB not initialized (schema version is 0), can't show any stats")
        return

    db.stats_print(cnx)

    print("\nStats by state:")
    by_state = db.stats_by_state(cnx)
    for state_id, name, cnt in by_state:
        print(f"{name:>18}({state_id:2}): {cnt}")

    print("\nStats by user:")
    by_user = db.stats_by_user(cnx)
    for name, user_id, cnt in by_user:
        print(f"{name:>18}({user_id:2}): {cnt}")

    cnx.close()


def histogram(args):
    """
    Generates frequency of photo frames for the whole sky.
    Buckets are 1x1 degree.

    :param args: _description_
    :type args: _type_
    :return: _description_
    :rtype: _type_
    """

    cnx = db.connect()
    tasks = db.tasks_get_filter(cnx, "imagename is not null AND he_solved_ra is not null AND state = 6")
    cnx.close()

    # This gets a list of coords (0-359, -90..90)

    # decl (89.99 .. -16)
    histo = np.zeros((180, 360))
    for t in tasks:
        ra = int(t[4])
        decl = int(t[5])
        histo[90 - decl][ra] += 1

    return histo


def groups(args):
    histo = histogram(args)

    min_frames = 200
    print(f"Showing groups with more than {min_frames} frame(s)")
    cnt = 0
    poi = []
    for decl in range(0, 180):
        for ra in range(0, 360):
            if histo[decl][ra] > min_frames:
                actual_decl = 90-decl
                actual_ra = ra/15
                poi.append(
                    {"cnt": int(histo[decl][ra]), "ra": actual_ra, "decl": actual_decl})
                cnt += 1

    poi = sorted(poi, key=lambda p: p['cnt'], reverse=True)

    conn = db.connect()

    for p in poi:
        # Get a list of objects in the vicinity
        ra = p['ra']
        decl = p['decl']
        objects = db.catalog_radius_get(conn, ra, decl, 1.0)
        tasks = db.tasks_radius_get(conn, ra, decl, 1.0)
        txt = f"{len(objects)} object(s), {len(tasks)} task(s):"
        for obj in objects:
            txt = txt + f"{obj[1]} "

        print(f"{p['cnt']} frame(s), ra={ra}, decl={decl} {txt}")

    conn.close()

def histogram_figure_get(args):
    """
    Generates plotly figure with histogram data.
    """

    histo = histogram(args)

    y_labels = list(range(90, -90, -1))
    y_labels = list(map(lambda a: str(a), y_labels))

    x_labels = list(map(lambda a: deg2rah(a), range(0, 360, 1)))

    labels = dict(x="Right Ascension (h:m/deg)",
                  y="Declination (deg)", color="# of frames")

    pandas = pd.DataFrame(histo)
    fig = px.imshow(pandas, labels=labels, y=y_labels, x=x_labels)

    fig['layout']['yaxis']['autorange'] = "reversed"

    return fig


def histogram_show(args):
    """
    Shows a histogram of image density for the whole sky
    """

    fig = histogram_figure_get(args)

    fig.show()
