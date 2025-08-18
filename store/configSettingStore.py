import requests

class ConfigSetting():
    def __init__(self):
        self.index = None
        self.maxStorageSize = None
        self.detectionSensitivity = None
        self.detectionPeriod = None
        self.continuousThreshold = None
        
    def getData(self, row: dict):
        keys = row.keys() if row else []
        for key in keys:
            self.setData(data=row, key=key)
            
    def setData(self, data:dict, key: str):
        try :
            setattr(self, key, data[key])
        except Exception as e :
            setattr(self, key, None)
            print('setData err : ', e)
            
class ConfigSettingStore():
    def __init__(self, backendHost = "192.168.0.31:7000"):
        self.configSettings:list[ConfigSetting] = []
        self.backendHost = backendHost
        
    def getData(self):
        try:
            response = requests.get(f"http://{self.backendHost}/forVideoServer/getConfigSetting")
            configSettingData:list[dict] = response.json()
        except Exception as e :
            configSettingData = []
            print('GroupStore.getData err : ', e)
        
        for row in configSettingData:
            config = ConfigSetting()
            config.getData(row)
            self.configSettings.append(config)
            
