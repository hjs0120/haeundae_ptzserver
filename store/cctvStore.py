import requests
from torch.multiprocessing import Value
import json
import pickle

class EventRegionValue:
    def __init__(self, roiPickle, roePickle):
        self.roiValue = Value('L', id(roiPickle))
        self.roeValue = Value('L', id(roePickle)) 

class DetectCCTV():
    def __init__(self):
        self.index = None
        self.onvifUrl = None
        self.onvifID = None
        self.onvifPW = None
        self.rtsp = None
        self.cctvName = None
        self.roi = None
        self.roe = None
        self.linkedPtzValue = None
        self.wsUrl = None
        self.detectionSensitivity = None
        
        self.roiPickle = pickle.dumps("")
        self.roePickle = pickle.dumps("")
        
        self.eventRegionUpdateFlag = Value('b', False)
        
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
            
    def setValue(self, eventRegionValue: EventRegionValue):
        roiPickle = pickle.dumps(json.dumps(self.roi))
        roePickle = pickle.dumps(json.dumps(self.roe))
        eventRegionValue(roiPickle, roePickle)
            
class PtzCCTV():
    def __init__(self):
        self.index = None
        self.onvifUrl = None
        self.onvifID = None
        self.onvifPW = None
        self.rtsp = None
        self.cctvName = None
        self.linkedCCTV = None
        self.autoZoomValue = None
        self.basePtzValue = None
        self.wsUrl = None

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
            print('data[key]', data[key])
        
class DetectCCTVStore():
    def __init__(self, backendHost = "192.168.0.31:7000"):
        self.detectCCTV:list[DetectCCTV] = []
        self.backendHost = backendHost
        
    def getData(self):
        try:
            response = requests.get(f"http://{self.backendHost}/forVideoServer/getDetectCCTVList")
            cctvInfoData:list[dict] = response.json()  
        except Exception as e :
            cctvInfoData = []
            print('DetectCCTVStore.getData err : ', e)
        
        for row in cctvInfoData:
            detectCCTV = DetectCCTV()
            detectCCTV.getData(row)
            self.detectCCTV.append(detectCCTV)
            
class PtzCCTVStore():
    def __init__(self, backendHost = "192.168.0.31:7000"):
        self.ptzCCTV:list[DetectCCTV] = []
        self.backendHost = backendHost
        
    def getData(self):
        try:
            response = requests.get(f"http://{self.backendHost}/forVideoServer/getPtzCCTVList")
            cctvInfoData:list[dict] = response.json()    
        except Exception as e :
            cctvInfoData = []
            print('DetectCCTVStore.getData err : ', e)
        
        for row in cctvInfoData:
            ptzCCTV = PtzCCTV()
            ptzCCTV.getData(row)
            self.ptzCCTV.append(ptzCCTV)
            
