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

def cache_access(cp, cmd, addr, nbytes):
    """ access the cache. returns relative cycle latency when data is available (cache.c). 
        Note: assumes 32-bit address and instruction.
    """
    vp, now, udata, repl_data = None, 0, None, None
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
        return cache_access(cache_il2, cmd, baddr, bsize)
    else:
        # access main memory, which is always done in the main simulator loop
        return 1; # return access latency

def test_simple():
    print("\n\n***** TEST CACHE *****")
    # Setup system
    sim_sdb = stat_new()

    # Create cache
    # l1 I-cache params: <name>:<nsets>:<bsize>:<assoc>:<repl>
    name, nsets, bsize, assoc, repl = "il1", 256, 8, 1, cache_char2policy(b'l') 
    cache_il1 = cache_create(name, nsets, bsize, False, 0, assoc, repl, il1_access_fn, 1)
    cache_config(cache_il1) # check if correctly constructed

    # Register all simulator stats
    cache_reg_stats(cache_il1, sim_sdb)
    stat_print_stats(sim_sdb)
    nbytes = ctypes.sizeof(md_inst_t) # 4 bytes/instruction

    print("\n\nAccess the cache 3 times to the same word...")
    pc = 0
    print("PC =", pc)
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes) # expected: 1 miss, 2 hits
    stat_print_stats(sim_sdb)

    print("\n\nAccess the cache 3 times to the next word (same block)...")
    pc += 4
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes) # expected: 1 miss, 5 hits
    stat_print_stats(sim_sdb)

    print("\n\nAccess the cache 3 times to the next word...")
    pc += 4
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes)
    cache_access(cache_il1, 'READ', pc, nbytes) # expected: 2 miss, 7 hits
    stat_print_stats(sim_sdb)

def test_trace():
    print("\n\n***** TEST INSTRUCTION TRACE *****")
    # Open trace
    df = pd.read_csv('test_trace.txt', dtype={'#':np.int64,'PC':np.int32})
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
    
    # Execute instruction trace
    nbytes = ctypes.sizeof(md_inst_t) # 4 bytes/instruction
    for pc in df.PC:
        cache_access(cache_il1, 'READ', pc, nbytes)
    
    print("\nExpected output (partial):")
    print("il1.accesses                  53459 # total number of accesses") # word hits + word misses
    print("il1.hits                      47366 # total number of hits") # = word hits
    print("il1.misses                     6093 # total number of misses") # = word misses
    print("il1.replacements               5837 # total number of replacements") # = block misses - number of sets
    print("\nActual output:")
    stat_print_stats(sim_sdb)
    """
sim-cache: SimpleScalar/PISA Tool Set version 3.0 of August, 2003.
Copyright (c) 1994-2003 by Todd M. Austin, Ph.D. and SimpleScalar, LLC.
All Rights Reserved. This version of SimpleScalar is licensed for academic
non-commercial use.  No portion of this work may be used by any commercial
entity, or for any commercial purpose, without the prior written permission
of SimpleScalar, LLC (info@simplescalar.com).

sim: command line: ./sim-cache -cache:dl1 none -cache:dl2 none -cache:il1 il1:256:32:1:l -cache:il2 none -tlb:itlb none -tlb:dtlb none -redir:prog /dev/null tests-pisa/bin.little/test-fmath

sim: simulation started @ Wed Jan 15 10:04:12 2020, options follow:

sim-cache: This simulator implements a functional cache simulator.  Cache
statistics are generated for a user-selected cache and TLB configuration,
which may include up to two levels of instruction and data cache (with any
levels unified), and one level of instruction and data TLBs.  No timing
information is generated.

# -config                     # load configuration from a file
# -dumpconfig                 # dump configuration to a file
# -h                    false # print help message
# -v                    false # verbose operation
# -d                    false # enable debug message
# -i                    false # start in Dlite debugger
-seed                       1 # random number generator seed (0 for timer seed)
# -q                    false # initialize and terminate immediately
# -chkpt               <null> # restore EIO trace execution from <fname>
# -redir:sim           <null> # redirect simulator output to file (non-interactive only)
# -redir:prog       /dev/null # redirect simulated program output to file
-nice                       0 # simulator scheduling priority
-max:inst                   0 # maximum number of inst's to execute
-cache:dl1               none # l1 data cache config, i.e., {<config>|none}
-cache:dl2               none # l2 data cache config, i.e., {<config>|none}
-cache:il1       il1:256:32:1:l # l1 inst cache config, i.e., {<config>|dl1|dl2|none}
-cache:il2               none # l2 instruction cache config, i.e., {<config>|dl2|none}
-tlb:itlb                none # instruction TLB config, i.e., {<config>|none}
-tlb:dtlb                none # data TLB config, i.e., {<config>|none}
-flush                  false # flush caches on system calls
-cache:icompress        false # convert 64-bit inst addresses to 32-bit inst equivalents
# -pcstat              <null> # profile stat(s) against text addr's (mult uses ok)

  The cache config parameter <config> has the following format:

    <name>:<nsets>:<bsize>:<assoc>:<repl>

    <name>   - name of the cache being defined
    <nsets>  - number of sets in the cache
    <bsize>  - block size of the cache
    <assoc>  - associativity of the cache
    <repl>   - block replacement strategy, 'l'-LRU, 'f'-FIFO, 'r'-random

    Examples:   -cache:dl1 dl1:4096:32:1:l
                -dtlb dtlb:128:4096:32:r

  Cache levels can be unified by pointing a level of the instruction cache
  hierarchy at the data cache hiearchy using the "dl1" and "dl2" cache
  configuration arguments.  Most sensible combinations are supported, e.g.,

    A unified l2 cache (il2 is pointed at dl2):
      -cache:il1 il1:128:64:1:l -cache:il2 dl2
      -cache:dl1 dl1:256:32:1:l -cache:dl2 ul2:1024:64:2:l

    Or, a fully unified cache hierarchy (il1 pointed at dl1):
      -cache:il1 dl1
      -cache:dl1 ul1:256:32:1:l -cache:dl2 ul2:1024:64:2:l



sim: ** starting functional simulation w/ caches **

sim: ** simulation statistics **
sim_num_insn                  53459 # total number of instructions executed
sim_num_refs                  16341 # total number of loads and stores executed
sim_elapsed_time                  1 # total simulation time in seconds
sim_inst_rate            53459.0000 # simulation speed (in insts/sec)
il1.accesses                  53459 # total number of accesses
il1.hits                      47366 # total number of hits
il1.misses                     6093 # total number of misses
il1.replacements               5837 # total number of replacements
il1.writebacks                    0 # total number of writebacks
il1.invalidations                 0 # total number of invalidations
il1.miss_rate                0.1140 # miss rate (i.e., misses/ref)
il1.repl_rate                0.1092 # replacement rate (i.e., repls/ref)
il1.wb_rate                  0.0000 # writeback rate (i.e., wrbks/ref)
il1.inv_rate                 0.0000 # invalidation rate (i.e., invs/ref)
ld_text_base             0x00400000 # program text (code) segment base
ld_text_size                  79920 # program text (code) size in bytes
ld_data_base             0x10000000 # program initialized data segment base
ld_data_size                  12288 # program init'ed `.data' and uninit'ed `.bss' size in bytes
ld_stack_base            0x7fffc000 # program stack segment base (highest address in stack)
ld_stack_size                 16384 # program initial stack size
ld_prog_entry            0x00400140 # program entry point (initial PC)
ld_environ_base          0x7fff8000 # program environment base address address
ld_target_big_endian              0 # target executable endian-ness, non-zero if big endian
mem.page_count                   30 # total number of pages allocated
mem.page_mem                   120k # total size of memory pages allocated
mem.ptab_misses                  31 # total first level page table misses
mem.ptab_accesses            748925 # total page table accesses
mem.ptab_miss_rate           0.0000 # first level page table miss rate
    """


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
        test_simple()
        test_trace()
