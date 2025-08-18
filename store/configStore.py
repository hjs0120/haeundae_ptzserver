import requests

class ServerConfig():
    def __init__(self):
        self.index = None
        self.host = None
        self.detectPortList = None
        self.ptzPortList = None
        self.wsIndex = None
        # self.isRunDetect = None
        
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
            
class ConfigStore():
    def __init__(self, backendHost = "192.168.0.31:7000"):
        self.config:list[ServerConfig] = []
        self.backendHost = backendHost
        
    def getData(self):
        try:
            response = requests.get(f"http://{self.backendHost}/forVideoServer/getConfig")
            configData:list[dict] = response.json()    
            pass
        except Exception as e :
            configData = []
            print('DetectCCTVStore.getData err : ', e)
        
        for row in configData:
            config = ServerConfig()
            config.getData(row)
            self.config.append(config)