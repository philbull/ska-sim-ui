#!/usr/bin/env python
"""
Insert scubed data into new database.
"""
import numpy as np
import db_interface as dbint


if __name__ == '__main__':
    # Create new instance of GalaxyTable
    galdb = dbint.GalaxyDB(dbname='sqlite:///scubed.db')
    tblname = 'scubed'
    
    # Build tblspec
    tspec = {}; ordering = {}
    with open("/data/skasims/scubed-1mil.header", 'r') as f:
        hdr = f.readline()[:-1].split(",")
        print hdr
        
        # Loop over fields and build table spec
        i = 0
        for field in hdr:
            ordering[field] = i; i += 1
            if field == 'id': continue # ID field already added
            if field == 'galaxyid' or field == 'box':
                # Only a couple of int fields
                tspec[field] = (field, dbint.Integer)
            else:
                # All other fields are floats
                tspec[field] = (field, dbint.Float)
    
    print tspec
        
    # Create table if needed
    if tblname not in galdb.tables.keys():
        
        # Create new table
        galdb.build_table(tblname, tspec)
        
        # Load cached npy data
        dat = np.load("/data/skasims/scubed-1mil.npy")
        assert dat.shape[0] < dat.shape[1]
        
        # Package into dict
        data_dict = {}
        for field in tspec.keys():
            data_dict[field] = dat[ordering[field]]
            
        # Store snapshot
        galdb.store_snapshot(tblname, data_dict, snapid=0, verbose=True)
        
    
    #galdb.load_table(tblname)
    res = galdb.query("select ra from scubed;")
    
