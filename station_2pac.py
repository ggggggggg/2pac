import numpy as np
import qcodes
from qcodes import VisaInstrument, Parameter, DelegateParameter
from lakeshore370 import LakeshoreModel370
from qcodes.station import Station
import cryocon24c
import labjacku3

from qcodes import config

# config.logger.start_logging_on_import = 'always'
# config.logger.file_level = "DEBUG"
# config.logger.console_level = "DEBUG"
# config.logger.logger_levels.pyisa = "DEBUG"
# qcodes.logger.start_all_logging()
# config.save_to_home()

def _make_station():
    ls = LakeshoreModel370("ls370", "ASRL/dev/ttyUSB1::INSTR")
    cryocon =  cryocon24c.Cryocon24C("cryocon", "ASRL/dev/ttyUSB0::INSTR")
    lj = labjacku3.LabjackU3("labjack")

    station = Station()
    station.add_component(ls)
    station.add_component(cryocon)
    station.add_component(lj)
    return station

_station = None

def get_station():
    global _station
    if _station is None:
        _station = _make_station()
    return _station