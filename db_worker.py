"""
Worker to asynchronously fetch database results.
"""
from celery import Celery
import celery.events.state as cstate
from celery.task.control import inspect as celery_inspect
import db_interface

# Set up app with connection to broker
app = Celery('dbqueries', backend='redis://localhost:6379/0', 
             broker='pyamqp://guest@localhost//', result_persistent=True)

app.conf.update(result_expires=db_interface.EXPIRY_TIME)

# Limit rate of submitting tasks
#app.control.rate_limit('db_worker.query_db', '20/m')


def list_tasks(task_id):
    #query = cstate.State()
    stats = celery_inspect(['celery', 'lynx'])
    print("TASK active:", stats.active())
    print("TASK scheduled:", stats.scheduled())
    print("TASK reserved:", stats.reserved())
    print("TASK revoked:", stats.revoked())
    print("TASK registered:", stats.registered())


@app.task(bind=True)
def query_db(self, dbname, sql_query):
    """
    Perform SQL query on database.
    """
    # Open database
    galdb = db_interface.GalaxyDB(dbname=dbname)
    
    # Update task status
    metadata = { 'db_name': dbname, 'sql_query': sql_query }
    self.update_state(state='PROGRESS', meta=metadata)
    
    task_db = db_interface.TaskDB(dbname='sqlite:///tasks.db', 
                                  tblname='sql_queries')
    task_db.update_task(uuid=self.request.id, status='running')
    
    # Run query and fetch results
    err = None; results = None; cols = None
    try:
        res = galdb.query(sql_query)
        cols = res.keys()
        results = res.fetchall()
        
        # Unpack into regular Python lists (which are serialisable)
        tbl = [[val for val in row] for row in results]
        
        # Add result to metadata list
        metadata['result'] = (cols, tbl, err)
        
        # Mark task as completed
        task_db.update_task(uuid=self.request.id, status='finished')
        
    except Exception as err:
        print("ERROR:", err)
        metadata['result'] = ([], [], str(err))
        task_db.update_task(uuid=self.request.id, status='failed')
    
    # Return results
    return metadata
    
