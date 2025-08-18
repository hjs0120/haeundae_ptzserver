import requests

class GroupConfig():
    def __init__(self):
        self.group = None
        self.targetDetectCCTV = None
        self.isRunDetect = None
        
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
            
class GroupStore():
    def __init__(self, backendHost = "192.168.0.31:7000"):
        self.group:list[GroupConfig] = []
        self.backendHost = backendHost
        
    def getData(self):
        try:
            response = requests.get(f"http://{self.backendHost}/forVideoServer/getGroupConfig")
            groupData:list[dict] = response.json()    
        except Exception as e :
            groupData = []
            print('GroupStore.getData err : ', e)
        
        for row in groupData:
            config = GroupConfig()
            config.getData(row)
            self.group.append(config)
            
