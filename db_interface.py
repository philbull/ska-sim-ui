"""
Interface to generic databases containing mock galaxy/halo catalogues, and a 
DB interface for tasks.
"""
from __future__ import print_function
import h5py
from sqlalchemy import create_engine, MetaData, Column, Table, \
                       Integer, String, Float, Sequence, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import sessionmaker

EXPIRY_TIME = 5*24*60*60 # seconds, how long to keep query results

statuses = {
    'finished': (0, '#60a917', 'status-finished'),
    'running':  (1, '#3e65ff', 'status-running'),
    'queued':   (2, '#fbd646', 'status-queued'),
    'failed':   (3, '#e51400', 'status-failed'),
}
status_map = {statuses[s][0]: s for s in statuses.keys()}


def abort_flush(*args, **kwargs):
    """
    Dummy function that does nothing. Used to block 'flush' directives, 
    effectively making a DB connection read-only.
    """
    print("flush detected")
    return


def sanitise_column_names(tblspec):
    """
    Replace illegal characters in DB column names.
    """
    # FIXME: Only does . for now
    tnew = {}
    for key in tblspec.keys():
        colname = key.replace(".", "_")
        tnew[colname] = tblspec[key]
    return tnew


def load_hdf5(fname, dset):
    """
    Load table from HDF5 file.
    """
    # Open file and get handle for specified group
    hfile = h5py.File(fname, 'r')
    ds = hfile[dset]
    # OutputN is a redshift slice
    
    # Construct table spec
    tspec = {}
    for key in ds.keys():
        if ":" not in key: # ignore complicated variables
            dtype = str(ds[key].dtype)
            _dtype = None
            if 'float' in dtype: _dtype = Float
            if 'int' in dtype: _dtype = Integer
            tspec[key] = (key, _dtype)
    
    # Sanitise column names
    tspec = sanitise_column_names(tspec)
    
    return hfile, ds, tspec


#===============================================================================
# Mock galaxy database handling
#===============================================================================

class GalaxyDB(object):
    
    def __init__(self, dbname, tblname=None, tblspec=None):
        """
        Create object and prepare connection.
        """
        # Open database
        self.db = create_engine(dbname)
        
        # Instance of global base class for entire DB
        self.DeclBase = declarative_base()
        
        # Create table if necessary info provided
        self.tables = {}; self.table_specs = {}
        if tblname is not None and tblspec is not None:
            self.build_table(tblname, tblspec)
    
    
    def build_table(self, tblname, tblspec):
        """
        Build declarative model for table.
        """
        # Construct proxy class that maps to SQL table
        if tblname in self.tables.keys():
            raise ValueError("Table '%s' already exists." % tblname)
        else:
            # Create new table and data model for it
            tblClass = type(tblname, (self.DeclBase,), 
                            {  '__tablename__': tblname, 
                               'id':      Column(Integer, primary_key=True),
                               'snapid':  Column(Integer) 
                            })
            # Add columns to class spec
            for i, key in enumerate(tblspec.keys()):
                fieldname, dtype = tblspec[key]
                setattr(tblClass, key, Column(dtype))
            
            # Create necessary metadata
            self.DeclBase.metadata.create_all(self.db)
            self.tables[tblname] = tblClass
            self.table_specs[tblname] = tblspec
    
    
    def load_table(self, tblname):
        """
        Load existing table from database.
        """
        # Check if table already loaded
        if tblname not in self.tables.keys():
            tbl = Table(tblname, self.DeclBase.metadata, autoload=True, 
                        autoload_with=self.db)
            self.tables[tblname] = tbl
            self.table_specs[tblname] = None # FIXME
        else:
            raise ValueError("Table '%s' already loaded." % tblname)
    
    
    def query(self, sql):
        """
        Execute textual SQL query.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        # Run an SQL query
        res = session.execute(text(sql))
        #session.close()
        return res
    
    
    def store_snapshot(self, tblname, hgroup, snapid, verbose=True):
        """
        Add data from HDF5 group to table.
        """
        if tblname not in self.tables.keys():
            raise ValueError("Table '%s' does not exist yet. Call "
                             "GalaxyDB.build_table() to create one." % tblname)
        
        assert isinstance(snapid, int), "snapid must be int"
        
        # Instantiate new session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        # Insert data in bulk
        tblspec = self.table_specs[tblname]
        tblClass = self.tables[tblname]
        nrows = hgroup[tblspec.keys()[0]].size
        print("Rows to be inserted:", nrows)
        for i in range(nrows):
            if verbose and i % 50 == 0:
                print("%1.1f%%" % (100.*float(i) / float(nrows)))
            row = {k: hgroup[tblspec[k][0]][i] for k in tblspec.keys()}
            row['snapid'] = snapid
            session.add(tblClass(**row))
        session.commit()
        session.close()


#===============================================================================
# Task database handling
#===============================================================================

class TaskDB(object):
    """
    DB interface to keep track of submitted tasks.
    """
    
    def __init__(self, dbname, tblname=None):
        """
        Create object and prepare connection.
        """
        # Open database
        self.db = create_engine(dbname)
        
        # Instance of global base class for entire DB
        self.DeclBase = declarative_base()
        
        # Create table specification
        tblspec = { 'uuid': String, 'query': String, 'status': Integer }
        
        # Create table if necessary info provided
        self.tables = {}; self.table_specs = {}
        if tblname is not None and tblspec is not None:
            self.build_table(tblname, tblspec)
    
    
    def build_table(self, tblname, tblspec):
        """
        Build declarative model for table.
        """
        # Construct proxy class that maps to SQL table
        if tblname in self.tables.keys():
            raise ValueError("Table '%s' already exists." % tblname)
        else:
            # Create new table and data model for it
            tblClass = type(tblname, (self.DeclBase,), 
                        { '__tablename__': tblname, 
                          'id': Column(Integer, primary_key=True),
                          'created': Column( DateTime(timezone=True), 
                                             server_default=func.now() )
                            })
            # Add columns to class spec
            for i, key in enumerate(tblspec.keys()):
                setattr(tblClass, key, Column(tblspec[key]))
            
            # Create necessary metadata
            self.DeclBase.metadata.create_all(self.db)
            self.tables[tblname] = tblClass
            self.table_specs[tblname] = tblspec
    
    
    def load_table(self, tblname):
        """
        Load existing table from database.
        """
        # Check if table already loaded
        if tblname not in self.tables.keys():
            tbl = Table(tblname, self.DeclBase.metadata, autoload=True, 
                        autoload_with=self.db)
            self.tables[tblname] = tbl
            self.table_specs[tblname] = None # FIXME
        else:
            raise ValueError("Table '%s' already loaded." % tblname)
    
    
    def query(self, sql):
        """
        Execute textual SQL query.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        # Run an SQL query
        res = session.execute(text(sql))
        #session.close()
        return res
    
    
    def add_task(self, uuid, query, status):
        """
        Add a task to the DB.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        TaskClass = self.tables['sql_queries'] # FIXME
        
        task = TaskClass(uuid=uuid, query=query, status=status)
        session.add(task)
        session.commit()
    
    def remove_task(self, uuid):
        """
        Remove a task from the DB.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        TaskClass = self.tables['sql_queries'] # FIXME
        res = session.query(TaskClass).filter( TaskClass.uuid.in_([uuid,]) )
        for row in res: session.delete(row)
        session.commit()
    
    def update_task(self, uuid, status):
        """
        Update status of a task.
        """
        if not isinstance(status, str):
            raise TypeError("'status' argument must be a string.")
        if status not in statuses.keys():
            raise ValueError("Status '%s' not recognised." % status)
        
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        # Fetch record corresponding to this UUID
        TaskClass = self.tables['sql_queries'] # FIXME
        res = session.query(TaskClass).filter( TaskClass.uuid.in_([uuid,]) ).all()
        
        # Update status
        for row in res: row.status = statuses[status][0] # status str -> int
        session.commit()
    
    
    def get_all(self):
        """
        Fetch all tasks.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        TaskClass = self.tables['sql_queries'] # FIXME
        res = session.query(TaskClass).order_by(TaskClass.created.desc()).all()
        return res
    
    
    def get_task_by_uuid(self, uuid):
        """
        Fetch details of a task by UUID.
        """
        # Set up session
        DBSession = sessionmaker(bind=self.db)
        session = DBSession()
        
        TaskClass = self.tables['sql_queries'] # FIXME
        res = session.query(TaskClass).filter(
                                              TaskClass.uuid.in_([uuid,])
                                             ).all()
        if len(res) < 1:
            return None # Not found
        elif len(res) == 1:
            return res
        else:
            # More than one found!
            print("WARNING: Multiple tasks found with the same UUID!")
            return res

if __name__ == '__main__':
    
    # Create new instance of GalaxyTable
    galdb = GalaxyDB(dbname='sqlite:///galacticus.db')
    tblname = 'galacticus'
    
    # Load HDF5 files into database
    if False:
        for i in range(9, 24):
            # Open HDF5 file and get table spec
            hfile, hgrp, tspec = load_hdf5(
                                    fname='../data/galacticus_pixel390654.hdf5', 
                                    dset="Outputs/Output%d/nodeData" % i)
            
            # Create table if needed
            if tblname not in galdb.tables.keys():
                galdb.build_table(tblname, tspec)
            
            # Store snapshot
            galdb.store_snapshot(tblname, hgrp, snapid=i, verbose=True)
            
            # Close HDF5 file
            hfile.close()
    
    #galdb.load_table(tblname)
    #print(galdb.tables[tblname]['hotHaloMass'])
    res = galdb.query("select blackHoleMass, lightconeRedshift from galacticus;")
    
    import numpy as np
    import pylab as plt
    
    m_bh, z = np.asarray( res.fetchall() ).T
    print(m_bh.size)
    
    plt.plot(z, m_bh, 'r.')
    plt.yscale('log')
    plt.show()
    
    
