"""
LEGO SPIKE Prime Backpacks
LPF2 class allows communication between LEGO SPIKE Prime and LEGO Backpacks
Version Date: 01/06/2020
Tufts Center for Engineering Education and Outreach
Tufts University

Add last NACK function to make sure when communication error, board can reset.
Updated on: 27/04/2024
"""
import machine, utime, gc
import math, struct
import utime, pyb

BYTE_NACK = 0x02
BYTE_ACK = 0x04
CMD_Type = 0x40  # set sensor type command
CMD_Select = 0x43  # sets modes on the fly
CMD_Mode = 0x49  # set mode type command
CMD_Baud = 0x52  # set the transmission baud rate
CMD_Vers = 0x5F  # set the version number
CMD_ModeInfo = 0x80  # name command
CMD_Data = 0xC0  # data command

CMD_LLL_SHIFT = 3
NACK_TryAttempt = 8

NAME, RAW, Pct, SI, SYM, FCT, FMT = 0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x80
DATA8, DATA16, DATA32, DATAF = 0, 1, 2, 3  # Data type codes

length = {
    "Int8": 1,
    "uInt8": 1,
    "Int16": 2,
    "uInt16": 2,
    "Int32": 4,
    "uInt32": 4,
    "float": 4,
}
format = {
    "Int8": "<b",
    "uInt8": "<B",
    "Int16": "<h",
    "uInt16": "<H",
    "Int32": "<l",
    "uInt32": "<L",
    "float": "<f",
}

def mode(
    name,
    size=1,
    type=DATA8,
    format="3.0",
    raw=[0, 100],
    percent=[0, 100],
    SI=[0, 100],
    symbol="",
    functionmap=[16, 0],
    view=True,
):
    fig, dec = format.split(".")
    fred = [
        name,
        [size, type, int(fig), int(dec)],
        raw,
        percent,
        SI,
        symbol,
        functionmap,
        view,
    ]
    return fred


class LPF2(object):
    def __init__(
        self,
        uartChannel,
        txPin,
        rxPin,
        modes,
        type=62,
        timer=4,
        freq=5,
    ):
        self.txPin = txPin
        self.rxPin = rxPin
        self.uart = machine.UART(uartChannel)
        self.txTimer = timer
        self.modes = modes
        self.current_mode = 0
        self.type = type
        self.connected = False
        self.payload = bytearray([])
        self.freq = freq
        self.oldbuffer = bytes([])
        self.textBuffer = bytearray(b"                ")
        self.LAST_NACK = 0
        self.LAST_HubCall = 0

    # -------- Payload definition

    def load_payload(self, type, array):  # note it must be a power of 2 length
        if isinstance(array, list):
            bit = math.floor(math.log2(length[type] * len(array)))
            bit = 4 if bit > 4 else bit  # max 16 bytes total (4 floats)
            array = array[
                : math.floor((2**bit) / length[type])
            ]  # max array size is 16 bytes
            value = b""
            for element in array:
                value += struct.pack(format[type], element)
        else:
            bit = int(math.log2(length[type]))
            value = struct.pack(format[type], array)
        payload = (
            bytearray([CMD_Data | (bit << CMD_LLL_SHIFT) | self.current_mode]) + value
        )
        self.payload = self.addChksm(payload)

    # ----- comm stuff

    def hubCallback(self, timerInfo):
        if self.connected:
            chr = self.uart.readchar()  # read in any heartbeat bytes
            while chr >= 0:
                if chr == 0:  # port has nto been setup yet
                    pass
                elif chr == BYTE_NACK:  # regular heartbeat pulse
                    pass
                    self.LAST_NACK += 1
                elif chr == CMD_Select:  # reset the mode
                    mode = self.uart.readchar()
                    cksm = self.uart.readchar()
                    if cksm == 0xFF ^ CMD_Select ^ mode:
                        self.current_mode = mode
                        # print(mode)
                elif chr == 0x46:  # sending over a string
                    zero = self.uart.readchar()
                    b9 = self.uart.readchar()
                    ck = 0xFF ^ zero ^ b9
                    if (zero == 0) & (b9 == 0xB9):  # intro bytes for the string
                        char = self.uart.readchar()  # size and mode
                        size = 2 ** ((char & 0b111000) >> 3)
                        mode = char & 0b111
                        ck = ck ^ char
                        for i in range(len(self.textBuffer)):
                            self.textBuffer[i] = ord(b" ")
                        for i in range(size):
                            self.textBuffer[i] = self.uart.readchar()
                            ck = ck ^ self.textBuffer[i]
                        print(self.textBuffer)
                        cksm = self.uart.readchar()
                        if cksm == ck:
                            pass
                elif chr == 0x4C:  # no idea what it is - but it sends a 0x20
                    thing = self.uart.readchar()
                    cksm = self.uart.readchar()
                    if cksm == 0xFF ^ 0x4C ^ thing:
                        pass
                else:
                    print(chr)
                chr = self.uart.readchar()

            size = self.writeIt(self.payload)  # send out the latest payload

            self.LAST_HubCall += 1
            # print(self.LAST_HubCall)
            # print("NACK lost: ", self.LAST_HubCall - self.LAST_NACK - 1)

            if (self.LAST_HubCall - self.LAST_NACK) > NACK_TryAttempt:
                self.LAST_HubCall = 0
                self.LAST_NACK = 0
                self.connected = False
                print("NACK Timeout, Reset!")

            if not size:
                self.connected = False

    def writeIt(self, array):
        # print(binascii.hexlify(array))
        return self.uart.write(array)

    def waitFor(self, char, timeout=2):
        starttime = utime.time()
        currenttime = starttime
        status = False
        while (currenttime - starttime) < timeout:
            utime.sleep_ms(5)
            currenttime = utime.time()
            if self.uart.any() > 0:
                data = self.uart.readchar()
                if data == ord(char):
                    status = True
                    break
        return status

    def addChksm(self, array):
        chksm = 0
        for b in array:
            chksm ^= b
        chksm ^= 0xFF
        array.append(chksm)
        return array

    # -----  Init and close

    def init(self):
        self.tx = machine.Pin(self.txPin, machine.Pin.OUT)
        self.rx = machine.Pin(self.rxPin, machine.Pin.IN)
        self.tx.value(0)
        utime.sleep_ms(500)
        self.tx.value(1)
        self.uart.init(baudrate=2400, bits=8, parity=None, stop=1)
        self.writeIt(b"\x00")

    def close(self):
        self.uart.deinit()
        self.sendTimer.callback(None)
        self.connected = False

    # ---- settup definitions

    def setType(self, sensorType):
        return self.addChksm(bytearray([CMD_Type, sensorType]))

    def defineBaud(self, baud):
        rate = baud.to_bytes(4, "little")
        return self.addChksm(bytearray([CMD_Baud]) + rate)

    def defineVers(self, hardware, software):
        hard = hardware.to_bytes(4, "big")
        soft = software.to_bytes(4, "big")
        return self.addChksm(bytearray([CMD_Vers]) + hard + soft)

    def padString(self, string, num, startNum):
        reply = bytearray([startNum])  # start with name
        reply += string
        exp = (
            math.ceil(math.log2(len(string))) if len(string) > 0 else 0
        )  # find the next power of 2
        size = 2**exp
        exp = exp << 3
        length = size - len(string)
        for i in range(length):
            reply += bytearray([0])
        return self.addChksm(bytearray([CMD_ModeInfo | exp | num]) + reply)

    def buildFunctMap(self, mode, num, Type):
        exp = 1 << CMD_LLL_SHIFT
        mapType = mode[0]
        mapOut = mode[1]
        return self.addChksm(
            bytearray([CMD_ModeInfo | exp | num, Type, mapType, mapOut])
        )

    def buildFormat(self, mode, num, Type):
        exp = 2 << CMD_LLL_SHIFT
        sampleSize = mode[0] & 0xFF
        dataType = mode[1] & 0xFF
        figures = mode[2] & 0xFF
        decimals = mode[3] & 0xFF
        return self.addChksm(
            bytearray(
                [
                    CMD_ModeInfo | exp | num,
                    Type,
                    sampleSize,
                    dataType,
                    figures,
                    decimals,
                ]
            )
        )

    def buildRange(self, settings, num, rangeType):
        exp = 3 << CMD_LLL_SHIFT
        minVal = struct.pack("<f", settings[0])
        maxVal = struct.pack("<f", settings[1])
        return self.addChksm(
            bytearray([CMD_ModeInfo | exp | num, rangeType]) + minVal + maxVal
        )

    def defineModes(self, modes):
        length = (len(modes) - 1) & 0xFF
        views = 0
        for i in modes:
            if i[7]:
                views = views + 1
        views = (views - 1) & 0xFF
        return self.addChksm(bytearray([CMD_Mode, length, views]))

    def setupMode(self, mode, num):
        self.writeIt(self.padString(mode[0], num, NAME))  # write name
        self.writeIt(self.buildRange(mode[2], num, RAW))  # write RAW range
        self.writeIt(self.buildRange(mode[3], num, Pct))  # write Percent range
        self.writeIt(self.buildRange(mode[4], num, SI))  # write SI range
        self.writeIt(self.padString(mode[5], num, SYM))  # write symbol
        self.writeIt(self.buildFunctMap(mode[6], num, FCT))  # write Function Map
        self.writeIt(self.buildFormat(mode[1], num, FMT))  # write format

    # -----   Start everything up

    def initialize(self):
        self.connected = False
        self.sendTimer = pyb.Timer(self.txTimer, freq=self.freq)  # default is 200 ms
        self.init()
        self.writeIt(
            self.setType(self.type)
        )  # set type to 35 (WeDo Ultrasonic) 61 (Spike color), 62 (Spike ultrasonic)
        self.writeIt(self.defineModes(self.modes))  # tell how many modes
        self.writeIt(self.defineBaud(115200))
        self.writeIt(self.defineVers(2, 2))
        num = len(self.modes) - 1
        for mode in reversed(self.modes):
            self.setupMode(mode, num)
            num -= 1
            utime.sleep_ms(5)

        self.writeIt(b"\x04")  # ACK
        # Check for ACK reply
        self.connected = self.waitFor(b"\x04")
        print("LUMP Init Success!" if self.connected else "LUMP Init Failed!")

        # Reset Serial to High Speed
        # pull pin low
        self.uart.deinit()
        if self.connected:
            tx = machine.Pin(self.txPin, machine.Pin.OUT)
            tx.value(0)
            utime.sleep_ms(10)

            # change baudrate
            self.uart.init(baudrate=115200, bits=8, parity=None, stop=1)
            self.load_payload("uInt8", 0)

            # start callback  - MAKE SURE YOU RESTART THE CHIP EVERY TIME (CMD D) to kill previous callbacks running
            self.sendTimer.callback(self.hubCallback)
        return


class Prime_LPF2(LPF2):
    def init(self):
        self.tx = machine.Pin(self.txPin, machine.Pin.OUT)
        self.rx = machine.Pin(self.rxPin, machine.Pin.IN)
        self.tx.value(0)
        utime.sleep_ms(500)
        self.tx.value(1)
        self.uart.init(baudrate=2400, bits=8, parity=None, stop=1)
        self.writeIt(b"\x00")


class EV3_LPF2(LPF2):
    def init(self):
        self.uart.init(baudrate=2400, bits=8, parity=None, stop=1)
        self.writeIt(b"\x00")

    def defineVers(self, hardware, software):
        return bytearray([])