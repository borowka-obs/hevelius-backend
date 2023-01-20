
import numpy as np
import pandas as pd
import plotly.express as px

from hevelius import db

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


def deg2rah(ra: float) -> str:
    """Converts Right Ascension specified in degrees (0..359) to hour
    (0..23.59)"""

    h = int(ra/15)
    m = int(ra - h*15) * 4

    return f"{h}h{m:02d}m ({ra}deg)"


def histogram(args):
    cnx = db.connect()
    tasks = db.tasks_get_filter(cnx, "imagename is not null AND he_solved_ra is not null AND state = 6")
    cnx.close()

    # This gets a list of coords (0-359, -90..90)
    histo = np.zeros((180, 360))
    for t in tasks:
        ra = int(t[4])
        decl = int(t[5])
        histo[90-decl, ra] += 1

    return histo


def groups(args):
    histo = histogram(args)

    min_frames = 200
    print(f"Showing groups with more than {min_frames} frame(s)")
    cnt = 0
    poi = []
    for decl in range(0, 360):
        for ra in range(0, 180):
            if histo[ra][decl] > min_frames:
                poi.append(
                    {"cnt": int(histo[ra][decl]), "ra": ra, "decl": decl})
                cnt += 1

    poi = sorted(poi, key=lambda p: p['cnt'], reverse=True)

    for p in poi:
        print(f"POI {p['cnt']}, ra={p['ra']}, decl={p['decl']}")


def histogram_show(args):

    histo = histogram(args)

    y_labels = list(range(90, -90, -1))
    y_labels = list(map(lambda a: str(a), y_labels))

    x_labels = list(map(lambda a: deg2rah(a), range(0, 360, 1)))

    labels = dict(x="Right Ascension (h:m/deg)",
                  y="Declination (deg)", color="# of frames")

    pandas = pd.DataFrame(histo)
    fig = px.imshow(pandas, labels=labels, y=y_labels, x=x_labels)

    fig['layout']['yaxis']['autorange'] = "reversed"

    fig.show()
