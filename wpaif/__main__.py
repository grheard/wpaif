import signal
import sys
import threading
import time

from project_common import cli
from project_common import logger
from project_common.mqtt import Mqtt
from .wpaif import WpaIf
from .config import Config


__signal = threading.Event()

clconfig = cli.parse_command_line_arguments()

Config(clconfig)

# Parse the logger configuration ahead of any other import
# in case a module also modifies the logger
logger.parse_logger_config(Config.instance().logger_config(),appname='wpaif')


def __signal_handler(signal, frame):
    try:
        logger.logger.info(f"Caught signal {signal}")
        __signal.set()
    except:
        sys.exit(-1)


if __name__ == '__main__':
    logger.logger.info('wpaif is starting')

    signal.signal(signal.SIGINT, __signal_handler)
    signal.signal(signal.SIGHUP, __signal_handler)

    Mqtt({'mqtt': {'clientid': 'wpaif'}})
    WpaIf()

    Mqtt.instance().connect()

    logger.logger.info('wpaif is started')

    while not __signal.is_set():
        time.sleep(0.250)

    logger.logger.info('wpaif is stopping')

    Mqtt.instance().disconnect()
    WpaIf.instance().stop()

    logger.logger.info('wpaif is stopped')
