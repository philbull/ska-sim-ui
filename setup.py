from __future__ import print_function
from setuptools import setup
import os, sys, subprocess

def checkout_ace():
    """
    Checkout ACE editor into a subdirectory.
    """
    # Check if directory exists
    if os.path.isdir("./static/ace-builds"):
        print("ACE directory already exists; no download needed.")
        return True
    
    try:
        # git clone into specific directory
        subprocess.call(["git", "clone", 
                         "https://github.com/ajaxorg/ace-builds.git", 
                         "static/ace-builds"])
    except:
        raise
    return True

setup_args = {
    'name':         'ska-sim-ui',
    'author':       'Phil Bull',
    'url':          'https://github.com/philbull/ska-sim-ui',
    'license':      'BSD',
    'version':      0.1,
    'description':  'Web interface for SKA simulations',
    'packages':     ['ska-sim-ui'],
    'package_dir':  {'ska-sim-ui': '.'},
    'install_requires': [],
    'include_package_data': False,
}

if __name__ == '__main__':
    
    checkout_ace()
    
    # FIXME: Not currently an installable package
    #apply(setup, (), setup_args)
    
    # 
    
