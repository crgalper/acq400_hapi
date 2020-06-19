#!/usr/bin/env python

"""
capture test. assume transient has been pre-configured
acq400_capture UUT1 [UUT2 ..]
where UUT1 is the ip-address or host name of first uut
example test client runs captures in a loop on one or more uuts

pre-requisite: UUT's are configured and ready to make a transient
capture
eg clk is running. soft trg enabled
eg transient length set.

loop continues "forever" until <CTRL-C>

usage: acq400_capture.py [-h] [--soft_trigger SOFT_TRIGGER]
                         [--transient TRANSIENT]
                         uuts [uuts ...]

run capture, with optional transient configuration

positional arguments:
  uuts                  uut1 [uut2..]

optional arguments:
  -h, --help            show this help message and exit
  --soft_trigger SOFT_TRIGGER
  --transient TRANSIENT
                        transient control string use commas rather than spaces

"""

import sys
import acq400_hapi
import argparse

def run_shot(args):
    uuts = [acq400_hapi.Acq400(u) for u in args.uuts]
    
    try:
        uuts[0].statmon.wait_stopped()

    except acq400_hapi.cleanup.ExitCommand:
        print("ExitCommand raised and caught")
    finally:
        print("Finally, going down")

# execution starts here

def run_main():
    parser = argparse.ArgumentParser(description='calls statmon.wait_stopped of given uuts')
    parser.add_argument('uuts', nargs='+', help='uut1 [uut2..]')
    run_shot(parser.parse_args())

if __name__ == '__main__':
    run_main()




