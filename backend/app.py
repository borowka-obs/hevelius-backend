from flask import Flask, render_template
import pandas as pd
import json
import plotly
import plotly.express as px

from hevelius import db_mysql as db

# By default, Flask searches for templates in the templates/ dir.
# Other params: debug=True, port=8080
app = Flask(__name__)

@app.route('/')
def root():
    return "Home🏠 EE"

@app.route('/histo')
def histogram():
   df = pd.DataFrame({
      'Fruit': ['Apples', 'Oranges', 'Bananas', 'Apples', 'Oranges',
      'Bananas'],
      'Amount': [4, 1, 2, 2, 4, 5],
      'City': ['SF', 'SF', 'SF', 'Montreal', 'Montreal', 'Montreal']
   })

   fig = px.bar(df, x='Fruit', y='Amount', color='City', barmode='group')
   graphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
   return render_template('histogram.html', graphJSON=graphJSON)

@app.route('/api/tasks/')
def tasks():

    cnx = db.connect()
    tasks = db.tasks_get_filter(cnx, "imagename is not null AND he_solved_ra is not null AND state = 6 LIMIT 10")
    cnx.close()

    t = [ {
        "task_id": 123,
        "ra": 12.34,
        "decl": 45.67,
        "descr": "some object"
    }]

    return tasks
