##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2018 Jorge Solla Rubiales <jorgesolla@gmail.com>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd
from .protocoldata import *

# Pulse types
class Pulse:
    INVALID, START, ZERO, ONE = range(4)

# Protocol stats
class Stat:
    WAIT_START, GET_BITS, WAIT_EOM, WAIT_ACK = range(4)

# Pulse times in milliseconds
timing = {
    Pulse.START:
        {
            'low': {
                'min': 3.5,
                'max': 3.9
            },
            'total': {
                'min': 4.3,
                'max': 4.7
            }
        },
    Pulse.ZERO:
        {
            'low': {
                'min': 1.3,
                'max': 1.7
            },
            'total': {
                'min': 2.05,
                'max': 2.75
            }
        },
    Pulse.ONE:
        {
            'low': {
                'min': 0.4,
                'max': 0.8
            },
            'total': {
                'min': 2.05,
                'max': 2.75
            }
        }
    }

class ChannelError(Exception):
    pass

class Decoder(srd.Decoder):
    api_version = 3
    id = 'cec'
    name = 'CEC'
    longname = 'HDMI Consumer Electronics Control protocol'
    desc = 'Consumer Electronics Control (CEC) protocol allows users to command and control devices connected through HDMI'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['hdmicec']
    channels = (
        {'id': 'CEC', 'name': 'CEC', 'desc': 'CEC bus data'},
    )

    annotations = (
        ('st', 'Start'),
        ('eom-0', 'End of message'),
        ('eom-1', 'Message continued'),
        ('nack', 'ACK not set'),
        ('ack', 'ACK set'),
        ('bits', 'Bits'),
        ('bytes', 'Bytes'),
        ('frames', 'Frames'),
        ('sections', 'Sections'),
        ('warnings', 'Warnings')
    )

    annotation_rows = (
        ('bits', 'Bits', (0,1,2,3,4,5)),
        ('bytes', 'Bytes', (6,)),
        ('frames', 'Frames', (7,)),
        ('sections', 'Sections', (8,)),
        ('warnings', 'Warnings', (9,))
    )

    def __init__(self):
        self.reset()

    def precalculate(self):
        # Restrict max length of ACK/NACK labels to 3 bit pulses
        bit_time = timing[Pulse.ZERO]['total']['min'];
        bit_time = bit_time * 2
        self.max_ack_len_samples = round((bit_time / 1000) * self.samplerate)

    def reset(self):
        self.stat = Stat.WAIT_START
        self.samplerate = None
        self.fall_start = None
        self.fall_end = None
        self.rise = None
        self.reset_frame_vars()

    def reset_frame_vars(self):
        self.eom = None
        self.bit_count = 0
        self.byte_count = 0
        self.byte = 0
        self.byte_start = None
        self.frame_start = None
        self.frame_end = None
        self.is_nack = 0
        self.cmd_bytes = []

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value
            self.precalculate()

    def set_stat(self, stat):
        self.stat = stat

    def handle_frame(self, is_nack):
        if self.fall_start == None or self.fall_end == None:
            return

        i = 0
        str = ""
        while i < len(self.cmd_bytes):
            str += "{:02x}".format(self.cmd_bytes[i]['val'])
            if i != (len(self.cmd_bytes) - 1):
                str += ":"
            i += 1

        self.put(self.frame_start, self.frame_end, self.out_ann, [7, [str]])

        i = 0
        operands = 0
        str = ""
        while i < len(self.cmd_bytes):
            # Parse header
            if i == 0:
                (src, dst) = decode_header(self.cmd_bytes[i]['val'])
                str = "[" + src + "] to [" + dst + "]"
            # Parse opcode
            elif i == 1:
                str += ": " + decode_opcode(self.cmd_bytes[i]['val'])
            # Parse operands
            else:
                if operands == 0:
                    str+= ", OPERANDS=["

                operands +=1
                str += hex(self.cmd_bytes[i]['val'])
                if i == len(self.cmd_bytes) - 1:
                    str += "]"
                else:
                    str += ","
            i += 1

        # Header only commands are PINGS
        if i == 1:
            str += ": PING"

        # Add extra information (acknowledgement of the command from the destination)
        if is_nack:
            str += " (NACK)"
        else:
            str += " (ACK)"

        self.put(self.frame_start, self.frame_end, self.out_ann, [8, [str]])

    def process(self):
        zero_time = ((self.rise - self.fall_start) / self.samplerate) * 1000.0
        total_time = ((self.fall_end - self.fall_start) / self.samplerate) * 1000.0

        pulse = Pulse.INVALID

        # VALIDATION: Identify pulse based on length of the low period
        for key in timing:
            if zero_time >= timing[key]['low']['min'] and zero_time <= timing[key]['low']['max']:
                pulse = key
                break

        # VALIDATION: Invalid pulse
        if pulse == Pulse.INVALID:
            self.set_stat(Stat.WAIT_START)
            self.put(self.fall_start, self.fall_end, self.out_ann, [9, ['Invalid pulse: Wrong timing']])
            return

        # VALIDATION: If waiting for start, discard everything else
        if self.stat == Stat.WAIT_START and pulse != Pulse.START:
            self.put(self.fall_start, self.fall_end, self.out_ann, [9, ['Expected START: BIT found']])
            return

        # VALIDATION: If waiting for ACK or EOM, only bit pulses (0/1) are expected
        if (self.stat == Stat.WAIT_ACK or self.stat == Stat.WAIT_EOM) and pulse == Pulse.START:
            self.put(self.fall_start, self.fall_end, self.out_ann, [9, ['Expected BIT: START received)']])
            self.set_stat(Stat.WAIT_START)

        # VALIDATION: ACK bit pulse remains high till the next frame (if any): Validate only min time of the low period
        if self.stat == Stat.WAIT_ACK and pulse != Pulse.START:
            if total_time < timing[pulse]['total']['min']:
                pulse = Pulse.INVALID
                self.put(self.fall_start, self.fall_end, self.out_ann, [9, ['ACK pulse below minimun time']])
                self.set_stat(Stat.WAIT_START)
                return

        # VALIDATION / PING FRAME DETECTION: Initiator doesn't sets the EOM = 1 but stops sending when ack doesn't arrive
        if self.stat == Stat.GET_BITS and pulse == Pulse.START:
            # Make sure we received a complete byte to consider it a valid ping
            if self.bit_count == 0:
                self.handle_frame(self.is_nack)
            else:
                self.put(self.frame_start, self.samplenum, self.out_ann, [9, ['ERROR: Incomplete byte received']])

            # Set wait start so we receive next frame
            self.set_stat(Stat.WAIT_START)

        # VALIDATION: Check timing of the bit (0/1) pulse in any other case (not waiting for ACK)
        if self.stat != Stat.WAIT_ACK and pulse != Pulse.START:
            if total_time < timing[pulse]['total']['min'] or total_time > timing[pulse]['total']['max']:
                self.put(self.fall_start, self.fall_end, self.out_ann, [9, ['Bit pulse exceeds total pulse timespan']])
                pulse = Pulse.INVALID
                self.set_stat(Stat.WAIT_START)
                return

        if pulse == Pulse.ZERO:
            bit = 0
        elif pulse == Pulse.ONE:
            bit = 1

        # STATE: WAIT START
        if self.stat == Stat.WAIT_START:
            self.set_stat(Stat.GET_BITS)
            self.reset_frame_vars()
            self.put(self.fall_start, self.fall_end, self.out_ann, [0, ['ST']])

        # STATE: GET BITS
        elif self.stat == Stat.GET_BITS:
            # Reset stats on first bit
            if self.bit_count == 0:
                self.byte_start = self.fall_start
                self.byte = 0

                # If 1st byte of the datagram, mark it as first
                if len(self.cmd_bytes) == 0:
                    self.frame_start = self.fall_start

            self.byte += (bit << (7 - self.bit_count))
            self.bit_count += 1
            self.put(self.fall_start, self.fall_end, self.out_ann, [5, [str(bit)]])

            if self.bit_count == 8:
                self.bit_count = 0
                self.byte_count += 1
                self.set_stat(Stat.WAIT_EOM)
                self.put(self.byte_start, self.samplenum, self.out_ann, [6, ["0x{:02x}".format(self.byte)]])
                self.cmd_bytes.append({'st': self.byte_start, 'ed': self.samplenum, 'val': self.byte})

        # STATE: WAIT EOM
        elif self.stat == Stat.WAIT_EOM:
            self.eom = bit;
            self.frame_end = self.fall_end;

            if self.eom:
                self.put(self.fall_start, self.fall_end, self.out_ann, [2, ['EOM=Y']])
            else:
                self.put(self.fall_start, self.fall_end, self.out_ann, [1, ['EOM=N']])

            self.set_stat(Stat.WAIT_ACK)

        # STATE: WAIT ACK
        elif self.stat == Stat.WAIT_ACK:
            # If a frame with broadcast destination is being sent, the ACK is inverted: A 0 is considered a NACK,
            # therefore we invert the value of the bit here, so we match the real meaning of it
            if (self.cmd_bytes[0]['val'] & 0x0F) == 0x0F:
                bit = ~bit & 0x01

            if (self.fall_end - self.fall_start) > self.max_ack_len_samples:
                ann_end = self.fall_start + self.max_ack_len_samples;
            else:
                ann_end = self.fall_end;

            if bit:
                # Any NACK detected in the frame is enough to consider the whole frame NACK'd
                self.is_nack = 1
                self.put(self.fall_start, ann_end, self.out_ann, [3, ['NACK']])
            else:
                self.put(self.fall_start, ann_end, self.out_ann, [4, ['ACK']])

            # After ACK bit, wait for new datagram or continue reading current one based on EOM value
            if self.eom:
                self.set_stat(Stat.WAIT_START)
                self.handle_frame(self.is_nack)
            else:
                self.set_stat(Stat.GET_BITS)

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def decode(self):
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')

        while True:
            # Wait for falling edge
            self.wait({0: 'f'})

            # Deceide if falling edge is start or end of pulse
            if self.fall_start == None:
                self.fall_start = self.samplenum
            else:
                self.fall_end = self.samplenum
                self.process()

                self.rise = None;
                self.fall_start = self.fall_end
                self.fall_end = None;

            # Wait for rising edge
            self.wait({0: 'r'})
            self.rise = self.samplenum
