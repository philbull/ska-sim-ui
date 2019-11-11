from flask import Flask
from flask import render_template, request, json, url_for, redirect, send_file
import db_interface
from db_interface import statuses, status_map, EXPIRY_TIME
from db_worker import query_db, list_tasks
import os, glob
from io import BytesIO

app = Flask(__name__)

# Mapping between survey types and icons
icon_spec = {
    'higal':        'fa-superpowers',
    'continuum':    'fa-asterisk',
    'intensitymap': 'fa-th-large',
}


def load_all_json_files(rootdir):
    """
    Load all JSON files in a given directory.
    """
    # Find all JSON files in the specs directory
    SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
    pattern = os.path.join(SITE_ROOT, rootdir, "*.json")
    files_json = glob.glob(pattern)
    
    # Load the files in turn
    files = []
    for s in files_json:
        try:
            d = json.load(open(s))
            files.append(d)
        except Exception as err:
            print("DEBUG: Error loading JSON file %s" % s)
            print(err)
            pass
    return files


#===============================================================================
# Main menu
#===============================================================================

@app.route("/")
def menu():
    
    # Load simulation info from JSON file and pull out necessary info
    specs = load_all_json_files("static/specs")
    cards = []
    for s in specs:
        card_spec = []
        
        # Get lists of tags and corresponding icons
        tags = " ".join([p['value'] for p in s['provides']])
        icons = [icon_spec[p['value']] for p in s['provides']]
        
        # Append fields to card spec
        card_spec.append(s['long-name'])
        card_spec.append(s['credit'])
        card_spec.append(tags)
        card_spec.append("/sim?name=%s" % s['name'])
        card_spec.append(icons)
        card_spec.append(s['short-desc'])
        
        cards.append(card_spec)
    
    return render_template('menu.html', cards=cards)


#===============================================================================
# SQL query handling
#===============================================================================

def load_db_specs(spec_name=None):
    """
    Loads database info, including field names and descriptions.
    """
    # Create list of catalogues, and field names from each catalogue
    specs = load_all_json_files("static/specs")
    cats = []; full_names = []; field_names = []; units = []; descs = []
    for s in specs:
        if 'catalogue' not in s.keys(): continue
        catspec = s['catalogue']
        tbl = catspec['table_name']
        cats.append(tbl)
        for fld in catspec['fields']:
            full_names.append("%s.%s" % (tbl, fld['name']))
            field_names.append("%s" % fld['name'])
            units.append("%s" % fld['units'])
            descs.append("%s" % fld['desc'])
    return cats, (full_names, field_names, units, descs)


@app.route("/query_catalogue")
def query():
    """
    Editor page for creating a new query.
    """
    # Load specs for all available DBs
    cats, field_specs = load_db_specs()
    full_names, field_names, units, descs = field_specs
    
    # Create list of example queries
    queries = load_all_json_files("static/example_queries")
    examples = [ (q['name'], q['long-name'], q['sql-query'], q['long-desc'])
                 for q in queries ]
    return render_template('query.html', catalogues=cats, examples=examples,
                           field_specs=zip(full_names, field_names, units, descs))


@app.route("/recent_queries")
def recent_queries():
    """
    Page listing recent queries.
    """
    # Initialise task database
    task_db = db_interface.TaskDB(dbname='sqlite:///tasks.db', 
                                  tblname='sql_queries')
    tasks = task_db.get_all()
    
    # Count the number of queries, and how many are running
    nqueries = len(tasks)
    nrunning = 0
    queries = []
    for t in tasks:
        # Track no. of running queries
        if t.status == statuses['running'][0]: nrunning += 1
        
        # Construct table
        s_id, s_col, s_tag = statuses[status_map[t.status]]
        qry = t.query[:80] + (t.query[80:] and '...') # truncate query
        queries.append( (qry, 'anon', t.created, s_col, s_tag, t.uuid) )
    
    return render_template('recent_queries.html', query_info=queries, 
                           num_queries=nqueries, num_queries_running=nrunning)


@app.route('/query_status/<query_id>', methods=['GET'])
def query_status(query_id):
    """
    Display the status or results of a query.
    """
    # Get query
    query = query_db.AsyncResult(query_id)
    
    # Check status of query
    if query.ready():
        # Query finished; render results
        print("*** FINISHED")
        sql_query = query.get()['sql_query']
        cols, tbl, err = query.get()['result']
        status = 'error' if err else 'finished'
        return render_template('show_query.html', sql_query=sql_query, 
                               sql_res=tbl, sql_cols=cols, sql_err=err, 
                               sql_max_rows=200, query_status=status, 
                               query_id=query_id)
    elif query.status == 'PROGRESS':
        # Query still in progress
        print("*** PROGRESS")
        sql_query = query.get()['sql_query']
        return render_template('show_query.html', sql_query=sql_query, 
                               sql_res=[], sql_cols=['In progress',], 
                               sql_err=None, sql_max_rows=200, 
                               query_status='inprogress', query_id=query_id)
    elif query.status == 'PENDING':
        # Query hasn't been registered yet or does not exist
        sql_query = "PENDING"
        sql_cols = ['Pending',]
        query_status = 'pending'
        
        # Load task database and check if expired
        task_db = db_interface.TaskDB(dbname='sqlite:///tasks.db', 
                                      tblname='sql_queries')
        tasks = task_db.get_task_by_uuid(query_id)
        if len(tasks) > 0:
            if status_map[tasks[0].status] == 'finished':
                # Task previously finished, but has now expired
                sql_query = tasks[0].query
                sql_cols = ['Query expired',]
                query_status = 'expired'
        
        return render_template('show_query.html', sql_query=sql_query, 
                               sql_res=[], sql_cols=sql_cols, 
                               sql_err=None, sql_max_rows=200, 
                               query_status=query_status, query_id=query_id, 
                               expiry_time="%d" % (EXPIRY_TIME/(24.*3600.)))
    else:
        # An unknown error occurred
        sql_query = "ERROR"
        print("*** ERROR")
        return render_template('show_query.html', sql_query=sql_query, 
                               sql_res=[], sql_cols=[], 
                               sql_err="Query returned an invalid status.", 
                               sql_max_rows=200, query_status='error', 
                               query_id=query_id)


@app.route('/sql_query', methods=['POST'])
def dispatch_sql_query():
    """
    Take a submitted SQL query and dispatch to a worker to complete in the 
    background.
    """
    sql_query = request.form['sql']
    
    # Initialise task DB
    task_db = db_interface.TaskDB(dbname='sqlite:///tasks.db', 
                                  tblname='sql_queries')
    
    # Run query asynchronously
    query = query_db.delay(dbname='sqlite:///galacticus.db', sql_query=sql_query)
    
    # Save task details
    task_db.add_task(uuid=query.id, query=sql_query, status=statuses['queued'][0])
    
    # Redirect to results page
    return redirect( url_for('query_status', query_id=query.id) )


@app.route('/query_remove/<query_id>', methods=['GET'])
def query_remove(query_id):
    """
    Remove a query from the task DB (and remove cached results).
    """
    # Fetch query by ID
    query = query_db.AsyncResult(query_id)
    
    # Delete from cache
    query.forget()
    
    # Delete from task DB
    # Initialise task database
    task_db = db_interface.TaskDB(dbname='sqlite:///tasks.db', 
                                  tblname='sql_queries')
    
    # Remove task
    task_db.remove_task(uuid=query.id)
    
    return redirect( url_for('recent_queries') )


@app.route('/download_result/<query_id>', methods=['GET'])
def download_result_as_table(query_id):
    """
    Download result of query as a CSV file.
    """
    # Get query
    query = query_db.AsyncResult(query_id)
    
    # Return nothing if query isn't ready
    if not query.ready(): return redirect("#")
    
    # Query finished; check if errored
    sql_query = query.get()['sql_query']
    cols, results, err = query.get()['result']
    if err: return redirect("#")
    
    # Query was successful; build results table
    tbl = BytesIO() # string as file
    
    # Add SQL query and column names in header
    tbl_str = ""
    tbl_str += "# %s\n" % sql_query.replace("\n", " ")
    tbl_str += "# %s\n" % ", ".join(cols)
    
    # Add data table to file
    for row in results:
        tbl_str += "%s\n" % ", ".join(str(item) for item in row)
    
    # Seek to start of file and begin download
    tbl.write(tbl_str.encode())
    tbl.seek(0)
    return send_file(tbl, attachment_filename="testing.csv", as_attachment=True)


#===============================================================================
# Misc. other features
#===============================================================================

@app.route("/about")
def about():
    return render_template('about.html')


@app.route("/contact")
def contact():
    return render_template('contact.html')


@app.route("/sim", methods=['GET'])
def sim():
    # Get the name of the sim we're looking for
    sim_name = request.args.get('name')
    
    # Find the spec corresponding to this simulation (if it exists)
    specs = load_all_json_files("static/specs")
    spec = None
    for s in specs:
        if s['name'] == sim_name:
            spec = s
            catspec = s['catalogue']
            tbl = catspec['table_name']
            
            # FIXME
            cats = []; field_names = []; units = []; descs = []
            cats.append(tbl)
            for fld in catspec['fields']:
                field_names.append("%s.%s" % (tbl, fld['name']))
                units.append("%s" % fld['units'])
                descs.append("%s" % fld['desc'])
    
    # Simulation wasn't found; show error
    if spec == None: 
        sim_name = "Not found!"
        return render_template('sim.html', sim_name=sim_name, desc="Not found.")
    
    # Get simulation name and description    
    return render_template('sim.html', sim_name=spec['long-name'], 
                           desc=spec['short-desc'])


@app.route("/select_area")
def select_area():
    return render_template('select_area.html')

"""
def query_mysql_db(sql):
    #Send user-defined SQL query to MySQL database.
    
    # Open connection to DB server
    conn = mysqldb.connect(host="127.0.0.1",
                           user="phil",
                           passwd="pass",
                           db="ska",
                           port=6603)
    c = conn.cursor()
    
    # Execute SQL query
"""
