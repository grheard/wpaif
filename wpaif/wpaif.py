import json
import os
import threading
import time
import base64
import queue

from project_common.logger import logger
from project_common.mqtt import Mqtt, mqtt
from . import wpacli
from .config import Config


ACTION = 'action'


class WpaIf():
    __instance = None


    @staticmethod
    def instance():
        if WpaIf.__instance is None:
            raise Exception('Instance has not been created.')

        return WpaIf.__instance


    def __init__(self):
        if WpaIf.__instance is not None:
            raise Exception('Singleton instance already created.')

        self.__wpa = wpacli.WpaCli(Config.instance().wpa_device())
        self.__wpa.set_command_callback(self.__wpa_callback)
        self.__wpa.start()

        Mqtt.instance().register_on_connect(self.__on_connect)

        self.__stop_event = threading.Event()

        self.__command_queue = queue.Queue()
        self.__response_queue = queue.Queue()

        self.__command_thread = threading.Thread(target=self.__command_thread_run)
        self.__command_thread.start()

        self.__status_thread = threading.Thread(target=self.__status_thread_run)
        self.__status_thread.start()

        WpaIf.__instance = self


    def stop(self):
        self.__stop_event.set()
        self.__status_thread.join()
        self.__command_thread.join()
        self.__wpa.stop()


    def __on_connect(self,client, userdata, flags, rc):
        if rc == mqtt.client.CONNACK_ACCEPTED:
            self.__subscribe()


    def __subscribe(self):
        sub = f'{Config.instance().topic()}/{ACTION}'
        logger.info(f'Subscribing to {sub}')
        Mqtt.instance().subscribe(sub,qos=2)
        Mqtt.instance().message_callback_add(sub,self.__on_mqtt_message)


    def __on_mqtt_message(self,client,userdata,message):
        try:
            logger.debug(f'{message.topic} -> {message.payload}')
        except:
            try:
                logger.debug(f'{message.topic} has an unknown payload of type {type(message.payload)}')
            except:
                logger.debug('I give up... recieved a really broken mqtt message.')

        if os.path.basename(message.topic) == ACTION:
            payload = {}
            try:
                payload = json.loads(message.payload)
            except:
                logger.warning(f'Received message payload is not json: "{message.payload}"')
                return

            if not wpacli.COMMAND in payload:
                logger.warning(f'Received message does not contain the "command" key: "{message.payload}"')
                return

            self.__command_queue.put(payload)


    def __wpa_callback(self,result):
        try:
            logger.debug(json.dumps(result))
        except:
            pass

        if not wpacli.COMMAND in result:
            raise KeyError('result is missing the \'command\' key')

        if not wpacli.RESULT in result:
            raise KeyError('result is missing the \'result\' key')

        if result[wpacli.COMMAND] == wpacli.STATUS:
            if result[wpacli.RESULT] != 'FAIL':
                self.__publish(result)

                try:
                    if result[wpacli.RESULT]['wpa_state'] == 'COMPLETED':
                        self.__wpa.signal_poll()
                except:
                    pass

        elif result[wpacli.COMMAND] == wpacli.SIGNAL_POLL:
            if result[wpacli.RESULT] != 'FAIL':
                self.__publish(result)

        else:
            self.__response_queue.put(result)


    def __status_thread_run(self):
        while not self.__stop_event.is_set():
            self.__wpa.status()
            time.sleep(1.0)


    def __command_thread_run(self):
        while not self.__stop_event.is_set():
            try:
                payload = self.__command_queue.get(block=True,timeout=0.01)
            except queue.Empty:
                continue

            if payload[wpacli.COMMAND] == wpacli.SCAN:
                response = self.__scan()

            elif payload[wpacli.COMMAND] == wpacli.LIST_NETWORKS:
                response = self.__list_networks()

            elif payload[wpacli.COMMAND] == wpacli.SET_NETWORK:
                response = self.__set_network(payload)

            elif payload[wpacli.COMMAND] == wpacli.ENABLE_NETWORK:
                response = self.__enable_network()

            elif payload[wpacli.COMMAND] == wpacli.DISABLE_NETWORK:
                response = self.__disable_network()

            else:
                logger.warning(f'Received unknown command "{payload[wpacli.COMMAND]}.')
                continue

            try:
                del response[wpacli.ARGS]
            except:
                pass

            self.__publish(response)


    def __wait_for_response(self) -> dict:
        try:
            response = self.__response_queue.get(block=True)#,timeout=10.0)
        except queue.Empty:
            logger.warning('Timeout waiting for a wpa response.')
            return None

        if response[wpacli.RESULT] == wpacli.FAIL:
            logger.warning(f'FAIL response for {response[wpacli.COMMAND]}.')
            return None

        return response


    def __scan(self) -> dict:
        self.__wpa.scan()
        response = self.__wait_for_response()
        if response is None:
            return {wpacli.COMMAND:wpacli.SCAN_RESULTS, wpacli.RESULT:wpacli.FAIL}

        start = time.time()
        stop = time.time()
        while (stop - start) < 10.0:
            self.__wpa.scan_results()
            response = self.__wait_for_response()
            if response is None:
                logger.warning('Error detected waiting for scan results.')
                return {wpacli.COMMAND: wpacli.SCAN, wpacli.RESULT: wpacli.FAIL}
            elif len(response[wpacli.RESULT]) != 0:
                response[wpacli.COMMAND] = wpacli.SCAN
                return response
            stop = time.time()

        logger.warning('No scan results produced in 10s')
        return {wpacli.COMMAND: wpacli.SCAN, wpacli.RESULT: wpacli.FAIL}


    def __list_networks(self) -> dict:
        self.__wpa.list_networks()
        response = self.__wait_for_response()
        if response is None:
            logger.warning('Failed to list networks.')
            return {wpacli.COMMAND: wpacli.LIST_NETWORKS, wpacli.RESULT: wpacli.FAIL}

        return response


    def __set_network(self,payload) -> dict:
        if not wpacli.SSID in payload:
            logger.warning(f'Received SET_NETWORK command does not contain the "ssid" key')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        if not wpacli.PSK in payload:
            logger.warning(f'Received SET_NETWORK command does not contain the "psk" key')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        # The ssid and psk are base64
        try:
            ssid = base64.b64decode(payload[wpacli.SSID]).decode('utf-8')
        except:
            logger.warning(f'Received SET_NETWORK command\'s ssid is not base64 encoded')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        try:
            psk = base64.b64decode(payload[wpacli.PSK]).decode('utf-8')
        except:
            logger.warning(f'Received SET_NETWORK command\'s psk is not base64 encoded')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        response = self.__list_networks()
        if response[wpacli.RESULT] == wpacli.FAIL:
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        # Remove any networks past 0 (if they exist)
        found = False
        if len(response[wpacli.RESULT]) != 0:
            for item in response[wpacli.RESULT]:
                if item[wpacli.NETWORK_ID] != '0':
                    self.__wpa.remove_network(item[wpacli.NETWORK_ID])
                    response = self.__wait_for_response()
                    if response is None:
                        logger.warning(f'Failed to remove network {item[wpacli.NETWORK_ID]}')
                else:
                    found = True

        if not found:
            self.__wpa.add_network()
            response = self.__wait_for_response()
            if response is None:
                logger.warning(f'Failed to add network')
                return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}
            if response[wpacli.RESULT] != '0':
                logger.warning(f'Added network expected "0" not "{response[wpacli.RESULT]}"')
                return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}
        else:
            self.__wpa.disable_network('0')
            response = self.__wait_for_response()
            if response is None:
                logger.warning(f'Failed to disable network ahead of setting values.')

        self.__wpa.set_network('0',wpacli.SSID,ssid)
        response = self.__wait_for_response()
        if response is None:
            logger.warning(f'Failed to set ssid')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        self.__wpa.set_network('0',wpacli.PSK,psk)
        response = self.__wait_for_response()
        if response is None:
            logger.warning(f'Failed to set psk')
            return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.FAIL}

        return {wpacli.COMMAND: wpacli.SET_NETWORK, wpacli.RESULT: wpacli.OK}


    def __enable_network(self) -> dict:
        self.__wpa.enable_network('0')
        response = self.__wait_for_response()
        if response is None:
            logger.warning(f'Failed to enable network')
            return {wpacli.COMMAND: wpacli.ENABLE_NETWORK, wpacli.RESULT: wpacli.FAIL}

        return response


    def __disable_network(self) -> dict:
        self.__wpa.disable_network('0')
        response = self.__wait_for_response()
        if response is None:
            logger.warning(f'Failed to disable network')
            return {wpacli.COMMAND: wpacli.DISABLE_NETWORK, wpacli.RESULT: wpacli.FAIL}

        return response


    def __publish(self,dictionary):
        try:
            p = json.dumps(dictionary)
            Mqtt.instance().publish(Config.instance().topic(),payload=p,qos=2)
            logger.debug(p)
        except Exception as ex:
            logger.warning(ex)
