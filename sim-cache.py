#!/usr/bin/python3
import os
import sys
import ctypes
import datetime
import numpy as np
import pandas as pd
import numpy.ctypeslib as npct
from ctypes import CFUNCTYPE, POINTER, c_void_p, c_char, c_int, c_uint8, c_uint32, c_int32, c_int64
from os.path import dirname, abspath, realpath, join, expanduser

# load shared library
filedir = dirname(abspath(__file__))
libdir = realpath(join(filedir, '.'))
print("load shared lib: {}".format(join(libdir, 'sim-cache.so')))
sim_cache = npct.load_library('sim-cache.so', expanduser(libdir))

# common data types
LP_c_char = POINTER(c_char)
LP_LP_c_char = POINTER(LP_c_char)

# data types defined by cache-sim
byte_t = c_uint8
counter_t = c_int64
tick_t = c_int64
md_inst_t = c_int32
md_addr_t = c_int32


"""
    Utility functions
"""

def init_env():
    """ initialize environment that can be used in C functions """
    argc = len(sys.argv)
    argv = (LP_c_char * (argc + 1))()
    envp = (LP_c_char * (len(os.environ) + 1))()
    for i, arg in enumerate(sys.argv):
        enc_arg = arg.encode('utf-8')
        argv[i] = ctypes.create_string_buffer(enc_arg)
        print("argv[{}] = {}".format(i, enc_arg))
    for i, env in enumerate(os.environ):
        enc_env = env.encode('utf-8')
        envp[i] = ctypes.create_string_buffer(enc_env)
    return argc, argv, envp

def main(argc, argv, envp):
    """ call the main routine from Python (main.c) """
    sim_cache.main.restype = None
    sim_cache.main.argtypes = [c_int, LP_LP_c_char, LP_LP_c_char]
    return sim_cache.main(argc, argv, envp)


"""
    Python bindings to Stat interface
"""

# function prototypes
def stat_new():
    """ create a new stats database (stat.c) """
    sim_cache.stat_new.restype = POINTER(stat_sdb_t)
    sim_cache.stat_new.argtypes = []
    return sim_cache.stat_new()

def stat_print_stats(sdb):
    """ print the value of all stat variables in stat database SDB (stat.c) """
    fd = ctypes.c_void_p.in_dll(sim_cache, 'stderr')
    sim_cache.stat_print_stats.restype = None
    sim_cache.stat_print_stats.argtypes = [POINTER(stat_sdb_t), c_void_p]
    return sim_cache.stat_print_stats(sdb, fd)

"""
    Python bindings to Cache interface
"""

# data structures
class cache_t(ctypes.Structure):
    """ creates a struct to match cache_t (cache.h) """
    f_callback = CFUNCTYPE(c_uint32, # return 
                           c_int32, c_int32, 
                           c_void_p, POINTER(tick_t)) # TODO: use enumerate type (first argument)
    
    _fields_ = [
        # parameters
        ('name',          LP_c_char),
        ('nsets',         c_int32),
        ('bsize',         c_int32),
        ('balloc',        c_int32),
        ('usize',         c_int32),
        ('assoc',         c_int32),
        ('policy',        c_int32), # TODO: use enumerate type
        ('hit_latency',   c_int32),
        
        # miss/replacement handler
        ('blk_access_fn', f_callback),
        
        # derived data, for fast decoding
        ('hsize',         c_int32),
        ('blk_mask',      md_addr_t),
        ('set_shift',     c_int32),
        ('set_mask',      md_addr_t),
        ('tag_shift',     c_int32),
        ('tag_mask',      md_addr_t),
        ('tagset_mask',   md_addr_t),
        
        # bus resource
        ('bus_free',      tick_t),
    
        # per-cache stats
        ('hits',          counter_t),
        ('misses',        counter_t),
        ('replacements',  counter_t),
        ('writebacks',    counter_t),
        ('invalidations', counter_t),
        
        # last block to hit, used to optimize cache processing
        ('last_tagset',   md_addr_t),
        ('last_blk',      c_void_p), # actual type: cache_blk_t*
        
        # data blocks 
        ('data',          POINTER(byte_t)),
        
        # variable-size tail array, this must be the LAST field in the structure
        ('sets',          POINTER(c_void_p)), # actual type: struct cache_set_t**
    ]

class stat_sdb_t(ctypes.Structure):
    """ creates a struct to match stat_sdb_t (stats.h) """
    _fields_ = [('stats', c_void_p), # types not matching...
                ('evaluator', c_void_p)]


# functions
def cache_char2policy(c):
    """ helper function to convert replacement policy to enumerate value (cache.c) """   
    sim_cache.cache_char2policy.restype = c_int32
    sim_cache.cache_char2policy.argtypes = [c_char]
    return sim_cache.cache_char2policy(c)

blk_access_fn_callback = CFUNCTYPE(c_uint32, c_int32, md_addr_t, c_int32, c_void_p, tick_t)
def cache_create(name, nsets, bsize, balloc, usize, assoc, policy, blk_access_fn, hit_latency):
    """ create cache (cache.c) """
    sim_cache.cache_create.restype = POINTER(cache_t)
    sim_cache.cache_create.argtypes = [LP_c_char, c_int32, c_int32, c_int32, c_int32, c_int32, 
                                       c_int32, blk_access_fn_callback, c_uint32]
    return sim_cache.cache_create(name.encode('utf-8'), nsets, bsize, balloc, usize, assoc, 
                                  policy, blk_access_fn, hit_latency)

def cache_config(cache):
    """ print cache info (cache.c) """
    fd = ctypes.c_void_p.in_dll(sim_cache, 'stderr')
    sim_cache.cache_config.restype = None
    sim_cache.cache_config.argtypes = [c_void_p, c_void_p]
    return sim_cache.cache_config(cache, fd)

def cache_reg_stats(cp, sdb):
    """ register cache performance counters (cache.c) """
    sim_cache.cache_reg_stats.restype = None
    sim_cache.cache_reg_stats.argtypes = [POINTER(cache_t), POINTER(stat_sdb_t)]
    return sim_cache.cache_reg_stats(cp, sdb)

def cache_access(cp, cmd, addr):
    """ access the cache. returns relative cycle latency when data is available (cache.c). 
        Note: assumes 32-bit address and instruction.
    """
    vp, nbytes, now, udata, repl_data = None, ctypes.sizeof(md_inst_t), 0, None, None
    cmd_int = 0 if cmd == 'READ' else 'WRITE'
    sim_cache.cache_access.restype = c_uint32
    sim_cache.cache_access.argtypes = [POINTER(cache_t), c_int32, md_addr_t, 
                                       c_void_p, c_int32, tick_t, LP_LP_c_char, c_void_p]
    return sim_cache.cache_access(cp, cmd_int, addr, vp, nbytes, now, udata, repl_data)


"""
    Main routine
"""

# define caches
cache_il1 = None
cache_il2 = None

# define custom block access function
@ctypes.CFUNCTYPE(c_uint32, c_int32, md_addr_t, c_int32, c_void_p, tick_t)
def il1_access_fn(cmd, baddr, bsize, blk, now):
    """ l1 inst cache block access handler function (sim-cache.c) """
    assert cmd == 0 or cmd == 1 # READ or WRITE
    if cache_il2:
        # access next level of inst cache hierarchy
        return cache_access(cache_il2, cmd, baddr)
    else:
        # access main memory, which is always done in the main simulator loop
        return 1; # return access latency


if __name__ == "__main__":
    # Small test case to check if Cache functionality works.
    #
    # 1. First run a normal cache simulation. Something like this:
    #
    #   ./sim-cache -cache:dl1 none -cache:dl2 none -cache:il1 il1:256:32:1:l -cache:il2 none -tlb:itlb none -tlb:dtlb none -redir:prog /dev/null tests-pisa/bin.little/test-fmath
    # 
    #   or (with GEN_TRACE == True)
    #
    #   python3 sim-cache.py -cache:dl1 none -cache:dl2 none -cache:il1 il1:256:32:1:l -cache:il2 none -tlb:itlb none -tlb:dtlb none -redir:prog /dev/null tests-pisa/bin.little/test-fmath
    #
    # 2. Execute this (with GEN_TRACE == False)
    #
    #   python3 sim-cache.py
    #
    GEN_TRACE = False 
    
    # Optional: generate trace file (out_trace.txt) using original simulator
    if GEN_TRACE:
        main(*init_env())
    else:
        # Open trace
        df = pd.read_csv('out_trace.txt', dtype={'#':np.int64,'PC':np.int32})
        df.set_index('#', inplace=True)
        
        # Setup system
        sim_sdb = stat_new()
        
        # Create cache
        # l1 I-cache params: <name>:<nsets>:<bsize>:<assoc>:<repl>
        name, nsets, bsize, assoc, repl = "il1", 256, 32, 1, cache_char2policy(b'l') 
        cache_il1 = cache_create(name, nsets, bsize, False, 0, assoc, repl, il1_access_fn, 1)
        cache_config(cache_il1) # check if correctly constructed
        
        # Register all simulator stats
        cache_reg_stats(cache_il1, sim_sdb)
        stat_print_stats(sim_sdb)
        
        # Access the Cache
        pc = df.PC[0]
        cache_access(cache_il1, 'READ', pc)
        
        print("TEST")
        stat_print_stats(sim_sdb)
        
        cache_access(cache_il1, 'READ', pc)
        print("TEST")
        stat_print_stats(sim_sdb)
