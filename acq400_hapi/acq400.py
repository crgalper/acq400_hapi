#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
acq400.py interface to one acq400 appliance instance

- enumerates all site services, available as uut.sX.knob
- simple property interface allows natural "script-like" usage
 - eg::

       uut1.s0.set_arm = 1

 - equivalent to running this on a logged in shell session on the UUT::

       set.site1 set_arm=1

 - monitors transient status on uut, provides blocking events
 - read_channels() - reads all data from channel data service.
  Created on Sun Jan  8 12:36:38 2017

  @author: pgm
"""

import threading
import re

import os
import errno
import signal
import sys
from . import netclient
import numpy as np
import socket
import timeit
import time

class AcqPorts:
    """server port constants"""
    TSTAT = 2235
    STREAM = 4210
    SITE0 = 4220
    SEGSW = 4250
    SEGSR = 4251
    DPGSTL = 4521
    GPGSTL= 4541
    GPGDUMP = 4543

    BOLO8_CAL = 45072
    DATA0 = 53000
    LIVETOP = 53998
    ONESHOT = 53999
    AWG_ONCE = 54201
    AWG_AUTOREARM = 54202
    MGTDRAM = 53990


class SF:
    """state constants"""
    STATE = 0
    PRE = 1
    POST = 2
    ELAPSED = 3
    DEMUX = 5

class STATE:
    """transient states"""
    IDLE = 0
    ARM = 1
    RUNPRE = 2
    RUNPOST = 3
    POPROCESS = 4
    CLEANUP = 5
    @staticmethod
    def str(st):
        if st==STATE.IDLE:
            return "IDLE"
        if st==STATE.ARM:
            return "ARM"
        if st==STATE.RUNPRE:
            return "RUNPRE"
        if st==STATE.RUNPOST:
            return "RUNPOST"
        if st==STATE.POPROCESS:
            return "POPROCESS"
        if st==STATE.CLEANUP:
            return "CLEANUP"
        return "UNDEF"

class Signals:
    EXT_TRG_DX = 'd0'
    INT_TRG_DX = 'd1'
    MB_CLK_DX = 'd1'

class StreamClient(netclient.Netclient):
    """handles live streaming data"""
    def __init__(self, addr):
        print("worktodo")

class Channelclient(netclient.Netclient):
    """handles post shot data for one channel.

    Args:
        addr (str) : ip address or dns name

        ch (int) : channel number 1..N

    """    
    def __init__(self, addr, ch):        
        netclient.Netclient.__init__(self, addr, AcqPorts.DATA0+ch) 

# on Linux, recv returns on ~mtu
# on Windows, it may buffer up, and it's very slow unless we use a larger buffer
    def read(self, ndata, data_size=2, maxbuf=0x400000):
        """read ndata from channel data server, return as np array.
        Args:
            ndata (int): number of elements

            data_size : 2|4 short or int

            maxbuf=4096 : max bytes to read per packet

        Returns:
            np: data array 

        * TODO buffer +=
   
         this is probably horribly inefficient probably better::

          retbuf = np.array(dtype, ndata)
          retbuf[cursor].

        """
        _dtype = np.dtype('i4' if data_size == 4 else 'i2')
        total_buffer = buffer = self.sock.recv(maxbuf)

        if int(ndata) == 0:
            while True:
                buffer = self.sock.recv(maxbuf)
                if not buffer:
                    return np.frombuffer(total_buffer, dtype=_dtype, count=-1)
                total_buffer += buffer

        while len(buffer) < ndata*data_size:
            buffer += self.sock.recv(maxbuf)

        return np.frombuffer(buffer, dtype=_dtype, count=ndata)


class ExitCommand(Exception):
    pass


def signal_handler(signal, frame):
    raise ExitCommand()

class Statusmonitor:
    """ monitors the status channel
    
    Efficient event-driven monitoring in a separate thread
    """
    st_re = re.compile(r"([0-9]) ([0-9]+) ([0-9]+) ([0-9]+) ([0-9])+" )

    def __repr__(self):
        return repr(self.logclient)
    def st_monitor(self):
        while self.quit_requested == False:
            st = self.logclient.poll()
            match = self.st_re.search(st)
            # status is a match. need to look at group(0). It's NOT a LIST!
            if match:
                statuss = match.groups()
                status1 = [int(x) for x in statuss]
                if self.trace:
                    print("%s <%s" % (repr(self), status1))
                if self.status != None:
#                    print("Status check %s %s" % (self.status0[0], status[0]))
                    if self.status[SF.STATE] != 0 and status1[SF.STATE] == 0:
                        print("%s STOPPED!" % (self.uut))
                        self.stopped.set()
                        self.armed.clear()
#                print("status[0] is %d" % (status[0]))
                    if status1[SF.STATE] == 1:
                        print("%s ARMED!" % (self.uut))
                        self.armed.set()
                        self.stopped.clear()
                    if self.status[SF.STATE] == 0 and status1[SF.STATE] > 1:
                        print("ERROR: %s skipped ARM %d -> %d" % (self.uut, self.status[0], status1[0]))
                        self.quit_requested = True
                        os.kill(self.main_pid, signal.SIGINT)
                        sys.exit(1)                                            
                self.status = status1
            elif self.trace > 1:
                print("%s <%s>" % (repr(self), st))

    def get_state(self):
        return self.status[SF.STATE]

    def wait_event(self, ev, descr):
    #       print("wait_%s 02 %d" % (descr, ev.is_set()))
        while ev.wait(0.1) == False:
            if self.quit_requested:
                print("QUIT REQUEST call exit %s" % (descr))
                sys.exit(1)

#        print("wait_%s 88 %d" % (descr, ev.is_set()))
        ev.clear()
#        print("wait_%s 99 %d" % (descr, ev.is_set()))        

    def wait_armed(self):
        """
        blocks until uut is ARMED                    
        """
        self.wait_event(self.armed, "armed")

    def wait_stopped(self):
        """
        blocks until uut is STOPPED                    
        """        
        self.wait_event(self.stopped, "stopped")

    trace = int(os.getenv("STATUSMONITOR_TRACE", "0"))

    def __init__(self, _uut, _status):
        self.quit_requested = False        
        self.trace = Statusmonitor.trace
        self.uut = _uut
        self.main_pid = os.getpid()
        self.status = _status
        self.stopped = threading.Event()
        self.armed = threading.Event()
        self.logclient = netclient.Logclient(_uut, AcqPorts.TSTAT)        
        self.st_thread = threading.Thread(target=self.st_monitor)
        self.st_thread.setDaemon(True)
        self.st_thread.start()             


class NullFilter:
    def __call__ (self, st):
        print(st)

null_filter = NullFilter()

class ProcessMonitor:
    st_re = re.compile(r"^END" )

    def st_monitor(self):
        while self.quit_requested == False:
            st = self.logclient.poll()
            self.output_filter(st)            
            match = self.st_re.search(st)
            if match:
                self.quit_requested = True

    def __init__(self, _uut, _filter):
        self.quit_requested = False
        self.output_filter = _filter
        self.logclient = netclient.Logclient(_uut, AcqPorts.MGTDRAM)
        self.logclient.termex = re.compile("(\n)")
        self.st_thread = threading.Thread(target=self.st_monitor)
        self.st_thread.setDaemon(True)
        self.st_thread.start()

class Acq400:
    """
    host-side proxy for Acq400 uut.

    discovers and maintains all site servers
    maintains a monitor thread on the monitor port
    handles multiple channel post shot upload

    Args:
        _uut (str) : ip-address or dns name

        monitor=True (bool) : set false to stub monitor, 
          useful for tracing on a second connection to an active system.
    """     
    @property 
    def mod_count(self):
        return self.__mod_count

    def init_site_client(self, site):
        svc = netclient.Siteclient(self.uut, AcqPorts.SITE0+site)
        self.svc["s%d" % site] = svc
        self.modules[site] = svc

        if self.awg_site == 0 and svc.module_name.startswith("ao"):
            self.awg_site = site
        self.__mod_count += 1


    @classmethod
    def create_uuts(cls, uut_names):
        """ create_uuts():  factory .. create them in parallel

        *** Experimental Do Not Use ***

        """
        uuts = []
        uut_threads = {}
        for uname in uut_names:
            uut_threads[uname] = \
                    threading.Thread(\
                        target=lambda u, l: l.append(cls(u)), \
                        args=(uname, uuts))
        for uname in uut_names:
            uut_threads[uname].start()
        for t in uut_threads:
            uut_threads[t].join(10.0)

        return uuts

    
    def __init__(self, _uut, monitor=True):
        self.NL = re.compile(r"(\n)")
        self.uut = _uut
        self.trace = 0
        self.save_data = None
        self.svc = {}
        self.modules = {}
        self.__mod_count = 0   
        # channel index from 1,..
        self.cal_eslo = [0, ]  
        self.cal_eoff = [0, ]
        self.mb_clk_min = 4000000
        
        s0 = self.svc["s0"] = netclient.Siteclient(self.uut, AcqPorts.SITE0)
        sl = s0.SITELIST.split(",")
        sl.pop(0)
        self.awg_site = 0
        site_enumerators = {} 
        for sm in sl:
            site_enumerators[sm] = \
                    threading.Thread(target=self.init_site_client,\
                        args=(int(sm.split("=").pop(0)),)\
                    )
        for sm in sl:
            site_enumerators[sm].start()

        for sm in sl:
#            print("join {}".format(site_enumerators[sm]))
            site_enumerators[sm].join(10.0)

# init _status so that values are valid even if this Acq400 doesn't run a shot ..
        _status = [int(x) for x in s0.state.split(" ")]
        if monitor:
            self.statmon = Statusmonitor(self.uut, _status)        


    def __getattr__(self, name):
        if self.svc.get(name) != None:
            return self.svc.get(name)
        else:
            msg = "'{0}' object has no attribute '{1}'"
            raise AttributeError(msg.format(type(self).__name__, name))

    def state(self):
        return self.statmon.status[SF.STATE]
    def post_samples(self):
        return self.statmon.status[SF.POST]
    def pre_samples(self):
        return self.statmon.status[SF.PRE]
    def elapsed_samples(self):
        return self.statmon.status[SF.ELAPSED]
    def demux_status(self):
        return self.statmon.status[SF.DEMUX]
    def samples(self):
        return self.pre_samples() + self.post_samples()

    def get_aggregator_sites(self):
        return self.s0.aggregator.split(' ')[1].split('=')[1].split(',')

    def fetch_all_calibration(self):
        print("Fetching calibration data")
        for m in (self.modules[int(c)] for c in self.get_aggregator_sites()):
            self.cal_eslo.extend(m.AI_CAL_ESLO.split(' ')[3:])
            self.cal_eoff.extend(m.AI_CAL_EOFF.split(' ')[3:])

    def scale_raw(self, raw, volts=False):
        for (sx, m) in list(self.modules.items()):
            if m.MODEL.startswith("ACQ43"):
                rshift = 8
            elif m.data32 == '1':
                # volts calibration is normalised to 24b
                if m.adc_18b == '1':
                    rshift = 14 - (8 if volts else 0)
                else:
                    rshift = 16 - (8 if volts else 0)
            else:
                rshift = 0
            break
        return np.right_shift(raw, rshift)

    def chan2volts(self, chan, raw):
        """ chan2volts(self, chan, raw) returns calibrated volts for channel

            Args:

               chan: 1..nchan

               raw:  raw bits to convert.

        """
        if len(self.cal_eslo) == 1:
            self.fetch_all_calibration()

        eslo = float(self.cal_eslo[chan])
        eoff = float(self.cal_eoff[chan])
        return np.add(np.multiply(raw, eslo), eoff)


    def read_chan(self, chan, nsam = 0):
        if nsam == 0:
            nsam = self.pre_samples()+self.post_samples()
        cc = Channelclient(self.uut, chan)
        ccraw = cc.read(nsam, data_size=(4 if self.s0.data32 == '1' else 2))

        if self.save_data:
            try:                
                os.makedirs(self.save_data)
            except OSError as exception:
                if exception.errno != errno.EEXIST:
                    raise

            with open("%s/%s_CH%02d" % (self.save_data, self.uut, chan), 'wb') as fid:
                ccraw.tofile(fid, '')

        return ccraw

    def nchan(self):
        return int(self.s0.NCHAN)

    def read_channels(self, channels=()):
        """read all channels post shot data.

        Returns:
            chx (list) of np arrays.
        """


        if channels == ():
            channels = list(range(1, self.nchan()+1))
        elif type(channels) == int:
            channels = (channels,)

    #      print("channels {}".format(channels))

        chx = []
        for ch in channels:
            if self.trace:
                print("%s CH%02d start.." % (self.uut, ch))
                start = timeit.default_timer()

            chx.append(self.read_chan(ch))

            if self.trace:
                tt = timeit.default_timer() - start
                print("%s CH%02d complete.. %.3f s %.2f MB/s" %
                      (self.uut, ch, tt, len(chx[-1])*2/1000000/tt))

        return chx

    # DEPRECATED
    def load_segments(self, segs):
        with netclient.Netclient(self.uut, AcqPorts.SEGSW) as nc:
            for seg in segs:
                nc.sock.send((seg+"\n").encode())
    # DEPRECATED
    def show_segments(self):
        with netclient.Netclient(self.uut, AcqPorts.SEGSR) as nc:
            while True:
                buf = nc.sock.recv(1024)
                if buf:
                    print(buf)
                else:
                    break            

    def clear_counters(self):
        for s in self.svc:
            self.svc[s].sr('*RESET=1')

    def set_sync_routing_master(self, clk_dx="d1", trg_dx="d0"):
        self.s0.SIG_SYNC_OUT_CLK = "CLK"
        self.s0.SIG_SYNC_OUT_CLK_DX = clk_dx
        self.s0.SIG_SYNC_OUT_TRG = "TRG"
        self.s0.SIG_SYNC_OUT_TRG_DX = trg_dx

    def set_sync_routing_slave(self):
        self.set_sync_routing_master()
        self.s0.SIG_SRC_CLK_1 = "HDMI"
        self.s0.SIG_SRC_TRG_0 = "HDMI"

    def set_sync_routing(self, role):
        # deprecated
        # set sync mode on HDMI daisychain
        # valid roles: master or slave
        if role == "master":
            self.set_sync_routing_master()
        elif role == "slave":            
            self.set_sync_routing_slave()
        else:
            raise ValueError("undefined role {}".format(role))

    def set_mb_clk(self, hz=4000000, src="zclk", fin=1000000):
        hz = int(hz)
        if src == "zclk":
            self.s0.SIG_ZCLK_SRC = "INT33M"
            self.s0.SYS_CLK_FPMUX = "ZCLK"
            self.s0.SIG_CLK_MB_FIN = 33333000
        elif src == "xclk":
            self.s0.SYS_CLK_FPMUX = "XCLK"
            self.s0.SIG_CLK_MB_FIN = 32768000
        else:
            self.s0.SYS_CLK_FPMUX = "FPCLK"
            self.s0.SIG_CLK_MB_FIN = fin

        if hz >= self.mb_clk_min:
            self.s0.SIG_CLK_MB_SET = hz
            print("Putting CLKDIV at 1")
            self.s1.CLKDIV = '1'
        else:
            for clkdiv in range(1,2000):
                if hz*clkdiv >= self.mb_clk_min:
                    self.s0.SIG_CLK_MB_SET = hz*clkdiv
                    print("Putting CLKDIV at {} on site 1".format(clkdiv))
                    self.s1.CLKDIV = clkdiv
                    return
            raise ValueError("frequency out of range {}".format(hz))

    def load_stl(self, stl, port, trace = False):
        termex = re.compile("\n")
        with netclient.Netclient(self.uut, port) as nc:
            lines = stl.split("\n")
            for ll in lines:
                if trace:
                    print("> {}".format(ll))
                if len(ll) < 2:
                    if trace:
                        print("skip blank")
                    continue
                if ll.startswith('#'):
                    if trace:
                        print("skip comment")
                    continue
                nc.sock.send((ll+"\n").encode())
                rx = nc.sock.recv(4096)
                if trace:
                    print("< {}".format(rx))
            nc.sock.send("EOF\n".encode())
            nc.sock.shutdown(socket.SHUT_WR)
            rx = nc.sock.recv(4096)
            if trace:
                print("< {}".format(rx))


    def load_gpg(self, stl, trace = False):
        #load_stl(self, stl, AcqPorts.GPGSTL, trace)
        self.load_stl(stl, AcqPorts.GPGSTL, trace)

        with netclient.Netclient(self.uut, AcqPorts.GPGDUMP) as nc: 
            while True:
                txt = nc.sock.recv(4096)
                if txt: 
                    sys.stdout.write(txt)                    
                    if txt.find("EOF") != -1:
                        break
                else:
                    break

    def load_dpg(self, stl, trace = False):
        #load_stl(self, stl, AcqPorts.DPGSTL, trace)
        self.load_stl(stl, AcqPorts.DPGSTL, trace)

    class AwgBusyError(Exception):
        def __init__(self, value):
            self.value = value
        def __str__(self):
            return repr(self.value)

    def load_awg(self, data, autorearm=False):
        if self.awg_site > 0:
            if self.modules[self.awg_site].task_active == '1':
                raise self.AwgBusyError("awg busy")
        port = AcqPorts.AWG_AUTOREARM if autorearm else AcqPorts.AWG_ONCE

        with netclient.Netclient(self.uut, port) as nc:
            nc.sock.send(data)
            nc.sock.shutdown(socket.SHUT_WR) 
            while True:
                rx = nc.sock.recv(128)
                if not rx or rx.startswith(b"DONE"):
                    break
            nc.sock.close()

    def run_service(self, port, eof="EOF", prompt='>'):
        txt = ""
        with netclient.Netclient(self.uut, port) as nc:
            while True:
                rx = nc.receive_message(self.NL, 256)
                txt += rx
                txt += "\n"
                print("{}{}".format(prompt, rx))
                if rx.startswith(eof):
                    break
            nc.sock.shutdown(socket.SHUT_RDWR)
            nc.sock.close() 

        return txt

    def run_oneshot(self):        
        with netclient.Netclient(self.uut, AcqPorts.ONESHOT) as nc:
            while True:
                rx = nc.receive_message(self.NL, 256)
                print("{}> {}".format(self.s0.HN, rx))
                if rx.startswith("SHOT_COMPLETE"):
                    break
            nc.sock.shutdown(socket.SHUT_RDWR)
            nc.sock.close()            

    def run_livetop(self):
        with netclient.Netclient(self.uut, AcqPorts.LIVETOP) as nc:
            print(nc.receive_message(self.NL, 256))
            nc.sock.shutdown(socket.SHUT_RDWR)
            nc.sock.close()


class Acq2106(Acq400):
    """ Acq2106 specialization of Acq400

    Defines features specific to ACQ2106
    """

    def __init__(self, _uut, monitor=True, has_mgtdram=False):
        print("acq400_hapi.Acq2106 %s" % (_uut))
        Acq400.__init__(self, _uut, monitor)
        self.mb_clk_min = 100000
        site = 13
        for sm in [ 'cA', 'cB']:
            try:
                self.svc[sm] = netclient.Siteclient(self.uut, AcqPorts.SITE0+site)
            except socket.error:
                print("uut {} site {} not populated".format(_uut, site))
            self.mod_count += 1
            site = site - 1
        if (has_mgtdram):
            try:
                self.svc['s14'] = netclient.Siteclient(self.uut, AcqPorts.SITE0+14)
            except socket.error:
                print("uut {} site {} not populated".format(_uut, site))            

    def set_mb_clk(self, hz=4000000, src="zclk", fin=1000000):
        print("set_mb_clk {} {} {}".format(hz, src, fin))
        Acq400.set_mb_clk(self, hz, src, fin)
        try:
            self.s0.SYS_CLK_DIST_CLK_SRC = 'Si5326'
        except AttributeError:
            print("SYS_CLK_DIST_CLK_SRC, deprecated")
        self.s0.SYS_CLK_OE_CLK1_ZYNQ = '1'

    def set_sync_routing_slave(self):
        Acq400.set_sync_routing_slave(self)
        self.s0.SYS_CLK_OE_CLK1_ZYNQ = '1'

    def set_master_trg(self, trg, edge = "rising", enabled=True):        
        if trg == "fp":
            self.s0.SIG_SRC_TRG_0 = "EXT" if enabled else "HOSTB"
        elif trg == "int":
            self.s0.SIG_SRC_TRG_1 = "STRIG"


    def run_mgt(self, _filter = null_filter):
        pm = ProcessMonitor(self.uut, _filter)
        while pm.quit_requested != True:
            time.sleep(1)



    



def run_unit_test():
    SERVER_ADDRESS = '10.12.132.22'
    if len(sys.argv) > 1:
        SERVER_ADDRESS = sys.argv[1]

    print("create Acq400 %s" %(SERVER_ADDRESS))
    uut = Acq400(SERVER_ADDRESS)
    print("MODEL %s" %(uut.s0.MODEL))
    print("SITELIST %s" %(uut.s0.SITELIST))
    print("MODEL %s" %(uut.s1.MODEL))

    print("Module count %d" % (uut.mod_count))
    print("POST SAMPLES %d" % uut.post_samples())

    for sx in sorted(uut.svc):
        print("SITE:%s MODEL:%s" % (sx, uut.svc[sx].sr("MODEL")))


if __name__ == '__main__':
    run_unit_test()

