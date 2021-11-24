import pathlib
import socket
import os
import tempfile
import queue
import threading
import select


STATUS = 'STATUS'
SIGNAL_POLL = 'SIGNAL_POLL'
SCAN = 'SCAN'
SCAN_RESULTS = 'SCAN_RESULTS'
LIST_NETWORKS = 'LIST_NETWORKS'
REMOVE_NETWORK = 'REMOVE_NETWORK'
ADD_NETWORK = 'ADD_NETWORK'
SELECT_NETWORK = 'SELECT_NETWORK'
ENABLE_NETWORK = 'ENABLE_NETWORK'
DISABLE_NETWORK = 'DISABLE_NETWORK'
SET_NETWORK = 'SET_NETWORK'
SSID = 'ssid'
PSK = 'psk'
BSSID = 'bssid'
NETWORK_ID = 'network id'
ATTACH = 'ATTACH'
DETACH = 'DETACH'
FAIL = 'FAIL'
OK = 'OK'
COMMAND = 'command'
RESULT = 'result'
ARGS = 'args'


def enumerate() -> list:
    return [x for x in pathlib.Path('/var/run/wpa_supplicant').iterdir() if x.is_socket()]


class WpaCli():

    def __init__(self, device):
        self.__device = device

        self.__stop_event = threading.Event()

        self.__queue = queue.Queue()

        self.__socket_file = f'{tempfile.gettempdir()}/wpacli-{os.getpid()}'
        self.__socket = socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.__socket.bind(self.__socket_file)

        self.__thread = threading.Thread(target=self.__run)

        self.__command_callback = None
        self.__attach_callback = None


    def set_command_callback(self,callback=None):
        self.__command_callback = callback


    def set_attach_callback(self,callback=None):
        self.__attach_callback = callback


    def start(self) -> bool:
        if not self.__thread.is_alive():
            self.__socket.connect(self.__device)
            self.__socket.setblocking(False)
            self.__thread.start()
            return True
        return False


    def stop(self):
        self.__stop_event.set()
        self.__thread.join()
        self.__socket.close()
        os.remove(self.__socket_file)


    def flush(self):
        self.__queue.join()


    def attach(self,callback=None):
        self.__queue_command((ATTACH,None,callback))


    def detach(self,callback=None):
        self.__queue_command((DETACH,None,callback))


    def status(self,callback=None):
        self.__queue_command((STATUS,None,callback))


    def signal_poll(self,callback=None):
        self.__queue_command((SIGNAL_POLL,None,callback))


    def scan(self,callback=None):
        self.__queue_command((SCAN,None,callback))


    def scan_results(self,callback=None):
        self.__queue_command((SCAN_RESULTS,None,callback))


    def list_networks(self,callback=None):
        self.__queue_command((LIST_NETWORKS,None,callback))


    def remove_network(self,id,callback=None):
        self.__queue_command((REMOVE_NETWORK,[str(id)],callback))


    def add_network(self,callback=None):
        self.__queue_command((ADD_NETWORK,None,callback))


    def set_network(self,id,param,value,callback=None):
        self.__queue_command((SET_NETWORK,[str(id),param,f'"{value}"'],callback))


    def select_network(self,id,callback=None):
        self.__queue_command((SELECT_NETWORK,[str(id)],callback))


    def enable_network(self,id,callback=None):
        self.__queue_command((ENABLE_NETWORK,[str(id)],callback))


    def disable_network(self,id,callback=None):
        self.__queue_command((DISABLE_NETWORK,[str(id)],callback))


    def __queue_command(self,_tuple):
        self.__queue.put(_tuple)


    def __run(self):
        command_count = 0
        command = None
        callback = None
        args = None

        while not self.__stop_event.is_set():
            if command is None:
                try:
                    (command,args,callback) = self.__queue.get(block=False)
                except queue.Empty:
                    command = None

                if not command is None:
                    if callback is None:
                        callback = self.__command_callback

                    command_count = 0
                    try:
                        if not command is None:
                            _command = command
                            if not args is None:
                                _command = f'{command} {" ".join(args)}'
                            self.__socket.send(str.encode(_command))
                    except:
                        if not callback is None:
                            try:
                                callback({COMMAND: command, RESULT: FAIL})
                            except:
                                pass
                        command = None
                        callback = None

            (rlist,_,_) = select.select([self.__socket],[],[],0.01)
            if len(rlist) != 0:
                result = self.__socket.recv(4096).decode('utf-8')
                if result[0] == '<':
                    result = {COMMAND: ATTACH, RESULT: result.rstrip()}
                    if not self.__attach_callback is None:
                        try:
                            self.__attach_callback(result)
                        except:
                            pass
                else:
                    result = self.__parse_result(command,args,result)
                    if not callback is None:
                        try:
                            callback(result)
                        except:
                            pass
                    command = None
                    callback = None

            else:
                if not command is None:
                    command_count += 1
                    if command_count >= 500:
                        command = None
                        callback = None


    def __parse_result(self,command,args,result) -> dict:
        _result = {COMMAND: command}

        if not args is None:
            _result[ARGS] = args

        if not result is None:
            if result.strip() == FAIL:
                _result[RESULT] = FAIL

            elif command == SCAN \
                or command == ADD_NETWORK \
                or command == REMOVE_NETWORK \
                or command == SET_NETWORK \
                or command == SELECT_NETWORK \
                or command == ENABLE_NETWORK \
                or command == DISABLE_NETWORK \
                or command == ATTACH \
                or command == DETACH:
                _result[RESULT] = result.strip()

            elif command == SCAN_RESULTS \
                or command == LIST_NETWORKS:
                lines = result.splitlines()
                # The labels are always on the first line of the results
                labels = [line.lstrip().rstrip() for line in lines[0].split('/')]
                entries = []
                for line in lines[1:]:
                    fields = line.split('\t')
                    entries.append(dict(zip(labels,fields)))
                _result[RESULT] = entries

            else:
                _result[RESULT] = self.__parse_key_equals_value_str(result)

        return _result


    def __parse_key_equals_value_str(self,string) -> dict:
        return dict(map(str.strip, sub.split('=',1)) for sub in string.splitlines() if '=' in sub)
