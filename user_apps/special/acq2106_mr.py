#!/usr/bin/env python

"""
configure and run a Multi Rate (MR) shot on one or more UUTs
pre-requisite: transient capture configured on all boxes

usage: acq2106_mr.py uut [uut2..]

example:
./user_apps/special/acq2106_mr.py --stl user_apps/STL/acq2106_mr3.stl --set_arm=1 acq2106_182

run_gpg

positional arguments:
  uut                   uut

optional arguments:
  -h, --help            show this help message and exit
  --trg TRG             trigger fp|soft|softloop|softonce
  --clk CLK             clk int|dX|notouch
  --mode MODE           mode
  --disable DISABLE     1: disable
  --stl STL             stl file
  --waterfall WATERFALL
                        d0,d1,d2,d3 waterfall [interval,hitime]
  --trace TRACE         trace wire protocol
  --hdmi_master HDMI_MASTER
                        clk, trg and gpg drive HDMI outputs
"""

import acq400_hapi
import argparse
import re

"""
denormalise_stl(args): convert from usec to clock ticks. round to modulo decval
"""
def denormalise_stl(args):
    lines = args.stl.splitlines()
    args.literal_stl = ""
    args.stl_literal_lines = []
    for line in lines:
        if line.startswith('#') or len(line) < 2:
            if args.verbose:
                print(line)
        else:
            action = line.split('#')[0]

            if action.startswith('+'): # support relative increments
                delayp = '+'
                action  = action[1:]
            else:
                delayp = ''

            delay, state = [int(x) for x in action.split(',')]
            delayk = int(delay * args.Fclk / 1000000)
            delaym = delayk - delayk % args.MR10DEC
            state = state << args.evsel0
            elem = "{}{:d},{:02x}".format(delayp, delaym, state)
            args.stl_literal_lines.append(elem)
            if args.verbose:
                print(line)

    return "\n".join(args.stl_literal_lines)

NONE = 'DSP0'     # TODO: explicit "NONE" source would be clearer.

def selects_trg_src(uut, src):
    def select_trg_src():
        uut.s0.SIG_SRC_TRG_0 = src
    return select_trg_src

def run_mr(args):
    args.uuts = [ acq400_hapi.Acq2106(u, has_comms=False) for u in args.uut ]
    master = args.uuts[0]
    with open(args.stl, 'r') as fp:
        args.stl = fp.read()

    lit_stl = denormalise_stl(args)

    master.s0.SIG_SRC_TRG_0 = NONE

    for u in args.uuts:
        acq400_hapi.Acq400UI.exec_args(u, args)
        u.s0.gpg_trg = '1,0,1'
        u.s0.gpg_clk = '1,1,1'
        u.s0.GPG_ENABLE = '0'
        u.load_gpg(lit_stl, args.verbose > 1)
        u.set_MR(True, evsel0=args.evsel0, evsel1=args.evsel0+1, MR10DEC=args.MR10DEC)
        u.s0.set_knob('SIG_EVENT_SRC_{}'.format(args.evsel0), 'GPG')
        u.s0.set_knob('SIG_EVENT_SRC_{}'.format(args.evsel0+1), 'GPG')
        u.s0.GPG_ENABLE = '1'

    if args.set_arm != 0:
        shot_controller = acq400_hapi.ShotController(args.uuts)
        shot_controller.run_shot(remote_trigger=selects_trg_src(master, args.trg0_src))


def run_main():
    parser = argparse.ArgumentParser(description='acq2106_mr')
    acq400_hapi.Acq400UI.add_args(parser, transient=True)
    parser.add_argument('--stl', default='none', type=str, help='stl file')
    parser.add_argument('--Fclk', default=40000000, type=int, help="base clock frequency")
    parser.add_argument('--trg0_src', default="EXT", help="trigger source, def:EXT opt: WRTT0")
    parser.add_argument('--set_arm', default='0', help="1: set arm" )
    parser.add_argument('--evsel0', default=4, type=int, help="dX number for evsel0")
    parser.add_argument('--MR10DEC', default=8, type=int, help="decimation value")
    parser.add_argument('--verbose', type=int, default=0, help='Print extra debug info.')
    parser.add_argument('uut', nargs='+', help="uuts")
    run_mr(parser.parse_args())


# execution starts here

if __name__ == '__main__':
    run_main()