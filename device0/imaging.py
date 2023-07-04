"""
Algae ~ Automated Target Positioning System
Electromagnetic Imaging Lab, University of Manitoba

Provides the class VNA and Switches which provides an
interface for setting up and controlling each device.

VNA commands follow the SCPI specification.

Hardware:
    Agilent E8363B PNA Network Analyzer
    Agilent 87050A Option K24 Multiport Test Set

Author: Noah Stieler, 2023
"""

import time
import pyvisa as visa

from gui.parameter import input_dict


class VNA:
    s_params = ['S11', 'S21', 'S12', 'S22']

    def __init__(self, resource: visa.Resource):
        self.resource = resource
        self.name = ""

        self.sp_to_measure = []
        self.p_ranges = {}

        self._set_parameter_ranges()

    @property
    def freq_list(self) -> list:
        li = []
        inc = (input_dict['freq_stop'].value - input_dict['freq_start'].value) / (input_dict['num_points'].value - 1)
        for i in range(int(input_dict['num_points'].value)):
            li.append(input_dict['freq_start'].value + i * inc)
        return li

    def __del__(self):
        if self.resource is None:
            return

        try:
            self.write('*RST')
            self.resource.close()
        except visa.errors.VisaIOError:
            pass
        except visa.errors.InvalidSession:
            pass

    def close(self) -> None:
        # Sending *RST prevents vna software crash
        self.write('*RST')
        self.resource.close()

    def initialize(self) -> None:
        self.resource.read_termination = '\n'
        self.resource.write_termination = '\n'

        self.name = self.resource.query('*IDN?')

        self.write('SYSTEM:FPRESET')

        self.display_on(False)

        # Using convention that parameter names are prefixed with 'parameter_'
        self.write('CALCULATE1:PARAMETER:DEFINE \'parameter_S11\', S11')
        self.write('CALCULATE1:PARAMETER:DEFINE \'parameter_S12\', S12')
        self.write('CALCULATE1:PARAMETER:DEFINE \'parameter_S21\', S21')
        self.write('CALCULATE1:PARAMETER:DEFINE \'parameter_S22\', S22')

        self.write('INITIATE:CONTINUOUS OFF')
        self.write('TRIGGER:SOURCE MANUAL')
        self.write('SENSE1:SWEEP:MODE HOLD')
        self.write('SENSE1:AVERAGE OFF')

        self.write('SENSE1:SWEEP:TYPE LINEAR')
        self.write('SENSE1:SWEEP:POINTS ' + str(int(input_dict['num_points'].value)))
        self.write('SENSE1:BANDWIDTH ' + str(input_dict['ifbw'].value))
        self.write('SENSE1:FREQUENCY:START ' + str(input_dict['freq_start'].value))
        self.write('SENSE1:FREQUENCY:STOP ' + str(input_dict['freq_stop'].value))
        # This is from the old software but the manual has a different syntax
        self.write('SOURCE1:POWER1 ' + str(input_dict['power'].value) + 'DBM')

        # Kind of arbitrary, chosen like this to ensure plenty of time to complete sweep
        # Extra important if data_point_count is large.
        self.resource.timeout = 100 * 1000  # time in milliseconds

        for s_param in VNA.s_params:
            if s_param in input_dict:
                if input_dict[s_param].value == 1:
                    self.sp_to_measure.append(s_param)

    def display_on(self, setting: bool) -> None:
        """Old software said VNA runs faster with display off,
        as mentioned in programming guide"""
        if setting:
            self.write('DISPLAY:VISIBLE ON')
        else:
            self.write('DISPLAY:VISIBLE OFF')

    def write(self, cmd: str) -> None:
        self.resource.write(cmd)

    def query(self, cmd: str) -> str:
        return self.resource.query(cmd)

    def fire(self) -> dict:
        """Trigger the VNA and return the data it collected."""
        self.write('INIT:IMM')
        # self.write('*WAI')  # *OPC? might be better because it stops the controller from attempting a read
        self.query('*OPC?')  # Controller waits until all commands are completed.

        # Using convention that parameter names are prefixed with 'parameter_'
        output = {}
        for s_parameter in self.sp_to_measure:
            self.write('CALCULATE1:PARAMETER:SELECT \'' + 'parameter_' + s_parameter + '\'')
            output[s_parameter] = self.query('CALCULATE:DATA? SDATA')

        return output

    def _set_parameter_ranges(self) -> None:
        """Gets all valid parameter ranges from the VNA.
        this is used when the 'run' button is pressed to ensure the
        user submitted valid data."""
        self.resource.read_termination = '\n'
        self.resource.write_termination = '\n'

        # Testing has confirmed this set up is required.
        self.write('SYSTEM:FPRESET')
        parameter_name = 'parameter_S21'
        self.write('CALCULATE1:PARAMETER:DEFINE \'' + parameter_name + '\', S21')
        self.write('INITIATE:CONTINUOUS OFF')
        self.write('TRIGGER:SOURCE MANUAL')
        self.write('SENSE1:SWEEP:MODE HOLD')
        self.write('SENSE1:AVERAGE OFF')
        self.write('SENSE1:SWEEP:TYPE LINEAR')

        self.p_ranges['num_points'] = (
            int(self.query('SENSE1:SWEEP:POINTS? MIN')),
            int(self.query('SENSE1:SWEEP:POINTS? MAX'))
        )
        self.p_ranges['ifbw'] = (
            float(self.query('SENSE1:BANDWIDTH? MIN')),
            float(self.query('SENSE1:BANDWIDTH? MAX'))
        )
        self.p_ranges['freq_start'] = (
            float(self.query('SENSE1:FREQUENCY:START? MIN')),
            float(self.query('SENSE1:FREQUENCY:START? MAX'))
        )
        self.p_ranges['freq_stop'] = (
            float(self.query('SENSE1:FREQUENCY:STOP? MIN')),
            float(self.query('SENSE1:FREQUENCY:STOP? MAX'))
        )
        self.p_ranges['power'] = (
            float(self.query('SOURCE1:POWER1? MIN')),
            float(self.query('SOURCE1:POWER1? MAX'))
        )


class Switches:
    """Commands must be terminated with a semicolon
    Previous software said that trans must be set before refl but
    both orders worked in my tests"""
    PORT_MIN = 1
    PORT_MAX = 24

    debounce_time = 0.03  # seconds

    def __init__(self, resource: visa.Resource):
        self.resource = resource

    def __del__(self):
        if self.resource is None:
            return

        try:
            self.resource.close()
        except visa.errors.VisaIOError:
            pass
        except visa.errors.InvalidSession:
            pass

    def close(self) -> None:
        self.resource.close()

    def initialize(self) -> None:
        self.write('*rst')  # reset

    def set_tran(self, port: int) -> None:
        """Port indices are 1-24 inclusive"""
        if port < Switches.PORT_MIN or port > Switches.PORT_MAX:
            raise SwitchInvalidPortException(port)

        self.write(f'tran_{Switches.pad_port_number(port)};')
        time.sleep(Switches.debounce_time)

    def set_refl(self, port: int) -> None:
        """Port indices are 1-24 inclusive"""
        if port < Switches.PORT_MIN or port > Switches.PORT_MAX:
            raise SwitchInvalidPortException(port)

        self.write(f'refl_{Switches.pad_port_number(port)}')
        time.sleep(Switches.debounce_time)

    def write(self, cmd: str) -> None:
        self.resource.write(cmd)

    @staticmethod
    def pad_port_number(port: int) -> str:
        """If the port is less than 9, it must be padded with a
        leading 0 in the command"""
        if port <= 9:
            return '0' + str(port)
        else:
            return str(port)


class SwitchInvalidPortException(Exception):
    """Raised when attempting to set the switch port outside
    the allowed range."""

    def __init__(self, attempted_port):
        self.attempted_port = attempted_port

    def display_message(self) -> None:
        print(f'SwitchInvalidPortException:'
              f'\n\tPort {self.attempted_port} is invalid.')
