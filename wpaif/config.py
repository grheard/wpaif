
COMMON = 'common'
TOPIC_ROOT = 'topic-root'
LOGGER = 'logger'
WPAIF = 'wpaif'
DEVICE = 'device'


class Config():
    __instance = None


    @staticmethod
    def instance():
        if Config.__instance is None:
            raise Exception('Instance has not been created.')

        return Config.__instance


    def __init__(self,config):
        if Config.__instance is not None:
            raise Exception('Singleton instance already created.')

        self.__parse_config(config)

        Config.__instance = self


    def __parse_config(self, config):
        self.__topic = WPAIF
        self.__logger_config = None

        if config is not None:
            if COMMON in config:
                if TOPIC_ROOT in config[COMMON]:
                    self.__topic = f"{config[COMMON][TOPIC_ROOT]}/{self.__topic}"

                if LOGGER in config[COMMON]:
                    self.__logger_config = config[COMMON]

            if WPAIF in config:
                if DEVICE in config[WPAIF]:
                    self.__wpa_device = config[WPAIF][DEVICE]

                if LOGGER in config[WPAIF]:
                    self.__logger_config = config[WPAIF][LOGGER]

        if not hasattr(self,'_Config__wpa_device'):
            raise Exception('Wpa device configuration must exist.')


    def topic(self) -> str:
        return self.__topic


    def logger_config(self) -> dict:
        return self.__logger_config


    def wpa_device(self) -> str:
        return self.__wpa_device