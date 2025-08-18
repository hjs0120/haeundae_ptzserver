from torch.multiprocessing import Queue
from onvif import ONVIFCamera
from zeep import Transport
from onvif.exceptions import ONVIFError
import threading
import math
import time
from queue import Empty
from store.cctvStore import PtzCCTV
from videoProcess.sharedData import SharedDetectData
from store.cctvStore import DetectCCTV

class Ptz:
    def __init__(self, ptzCCTV: PtzCCTV, port, sharedDetectDataList: list[SharedDetectData], detectCCTVList: list[DetectCCTV]):
        self.ip = ptzCCTV.onvifUrl
        self.port = int(port)
        self.username = ptzCCTV.onvifID
        self.password = ptzCCTV.onvifPW
        self.basePtzValue = ptzCCTV.basePtzValue
        self.autoZoomValue = ptzCCTV.autoZoomValue
        
        self.onMove = False
        self.baseFlag = True
        
        self.sharedDetectDataList = sharedDetectDataList
        self.detectCCTVList = detectCCTVList
        
        self.ptzCoordintes = []
        self.ptzFlag = 0
        
    def connect(self):
        try:
            transport = Transport(timeout=1000)
            self.cam = ONVIFCamera(self.ip, self.port, self.username, self.password, transport=transport, wsdl_dir='/usr/local/wsdl/')
            
            self.media = self.cam.create_media_service()
            self.profile = self.media.GetProfiles()[0]
            self.ptz = self.cam.create_ptz_service()
            
            self.configRequest = self.ptz.create_type('GetConfigurationOptions')
            self.configRequest.ConfigurationToken = self.profile.PTZConfiguration.token
            self.ptzConfigOptions = self.ptz.GetConfigurationOptions(self.configRequest)
            
            self.absRequest = self.ptz.create_type('AbsoluteMove')
            self.absRequest.ProfileToken = self.profile.token
            self.relRequest = self.ptz.create_type('RelativeMove')
            self.relRequest.ProfileToken = self.profile.token

            self.xMax = float(self.ptzConfigOptions.Spaces.AbsolutePanTiltPositionSpace[0].XRange.Max)
            self.xMin = float(self.ptzConfigOptions.Spaces.AbsolutePanTiltPositionSpace[0].XRange.Min)
            self.yMax = float(self.ptzConfigOptions.Spaces.AbsolutePanTiltPositionSpace[0].YRange.Max)
            self.yMin = float(self.ptzConfigOptions.Spaces.AbsolutePanTiltPositionSpace[0].YRange.Min)
            self.zMax = float(self.ptzConfigOptions.Spaces.ZoomSpeedSpace[0].XRange.Max)
            self.zMin = float(self.ptzConfigOptions.Spaces.ZoomSpeedSpace[0].XRange.Min)
            
            self.status = self.ptz.GetStatus({'ProfileToken': self.profile.token})
            print("Connected to ONVIF camera successfully.")
            return True
        
        except Exception as e:
            print(f"Error connecting to the ONVIF device: {e}")
            return False
        
    def AutoControlProc(self, ptzAvailable):
        for index, sharedDetectData in enumerate(self.sharedDetectDataList):
            getCoordThread = threading.Thread(target=self.getCoordThread, args=[sharedDetectData.ptzCoordsQueue, index], daemon=True)
            getCoordThread.start()
        
        if not ptzAvailable:
            return
        
        moveToBaseThread = threading.Thread(target=self.moveToBaseThread, daemon= True)
        moveToBaseThread.start()
        prevPtzCoordinates = []
        
        while True :
            if self.ptzCoordintes != prevPtzCoordinates and self.ptzCoordintes != []:
                prevPtzCoordinates = self.ptzCoordintes
                controlPtzThread = threading.Thread(target=self.controlPtzThread, args=[self.ptzCoordintes], daemon=True)
                controlPtzThread.start()
            time.sleep(0.5)
    
    def controlPtzThread(self, ptzCoordintes):
        if len(self.linkedPtzValue) < 4:
            return
        pan, tilt = self.normalizePointInBaseRect(ptzCoordintes, self.linkedPtzValue)
        pan, tilt = self.changeToPanTilt(pan, tilt)
        self.autoZoomValue
        self.absoluteMove(pan, tilt, 0.2)
            
    def getCoordThread(self, eventObjectQueue: Queue, processindex: int):
        flagID = processindex + 1    
        eventObjectCoordinates = []
        prevPtzCoord = []

        while True:
            try:
                coordinate = eventObjectQueue.get_nowait()
            except Empty as e:
                time.sleep(0.5)
                continue
            
            if coordinate is not None:
                eventObjectCoordinates.append(coordinate)
                continue
            
            if len(eventObjectCoordinates) == 0: 
                self.ptzCoordintes = []
                prevPtzCoord = []
                self.ptzFlag = 0
                continue
            
            if self.ptzFlag == 0:
                self.ptzFlag = flagID
                prevPtzCoord = []
                
            if self.ptzFlag != flagID :
                eventObjectCoordinates = []
                continue
            
            self.linkedPtzValue = self.detectCCTVList[processindex].linkedPtzValue
            self.autoZoomValue = self.detectCCTVList[processindex].autoZoomValue
            
            if prevPtzCoord == [] :
                prevPtzCoord = eventObjectCoordinates[0]
                self.ptzCoordintes = prevPtzCoord
                eventObjectCoordinates = []
                continue
            
            minDist =  self.calculatDistance(prevPtzCoord, eventObjectCoordinates[0])
            minCoord = eventObjectCoordinates[0]
            for eventObjectCoordinate in eventObjectCoordinates:
                dist = self.calculatDistance(prevPtzCoord, eventObjectCoordinate)
                if dist < minDist:
                    minDist = dist
                    minCoord = eventObjectCoordinate
                    
            prevPtzCoord = minCoord
            self.ptzCoordintes = prevPtzCoord
            
            eventObjectCoordinates = []
                  
    def calculatDistance(self, point1, point2):
        x1, y1 = point1
        x2, y2 = point2
        distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        return distance         
            
    def calculatePointsDirection(self, startPoint, endPoint, precision=10):
        MoveParameter = 0.03
        
        dx = endPoint[0] - startPoint[0]
        dy = endPoint[1] - startPoint[1]
        angleRad = math.atan2(dy, dx)
        newStartPoint = [0, 0]
        
        direction = [math.cos(angleRad), math.sin(angleRad)]
        scale = MoveParameter / math.sqrt(direction[0]**2 + direction[1]**2)
        scaled_direction = [coord * scale for coord in direction]
        
        direction = [round(coord, precision) for coord in scaled_direction]
        
        point1 = newStartPoint
        point2 = [newStartPoint[0] + direction[0], -(newStartPoint[1] + direction[1])]
        
        return point1, point2
    
    def calculatekeyboardDirection(self, W, A, S, D):
        MoveParameter = 0.01
        pan, tilt = 0, 0
        if W: tilt += MoveParameter
        if A: pan -= MoveParameter
        if S: tilt -= MoveParameter
        if D: pan += MoveParameter
        return pan, tilt
    
    def absoluteMove(self, pan, tilt, zoom):
        self.absRequest.Position = {
            'PanTilt' : {'x': pan, 'y': tilt},
            'Zoom' : {'x' : zoom}
        }
        try:
            self.ptz.Stop({'ProfileToken': self.absRequest.ProfileToken})
            self.ptz.AbsoluteMove(self.absRequest)
        except ONVIFError as e:
            self.absoluteMove()
            print(f"ONVIFError : {e}")
        
    def moveToBaseThread(self):
        prevTime = time.time()
        prevPosition = self.ptz.GetStatus({'ProfileToken': self.profile.token}).Position
        while True:
            try:
                currentTime = time.time()
                currentPosition = self.ptz.GetStatus({'ProfileToken': self.profile.token}).Position
                if prevPosition != currentPosition:
                    prevPosition = currentPosition
                    prevTime = currentTime
                    if self.onMove == False:
                        self.onMove = True
                        if self.baseFlag == True :
                            self.baseFlag = False
                else :
                    if currentTime - prevTime > 0.5:
                        if self.onMove == True:
                            self.onMove = False
                    if currentTime - prevTime > 25:
                        if self.basePtzValue != None and self.basePtzValue != []:
                            if self.baseFlag == False :
                                pan, tilt = self.changeToPanTilt(self.basePtzValue[0], self.basePtzValue[1])
                                self.absoluteMove(pan, tilt, self.basePtzValue[2])
                                self.baseFlag = True
                            
                time.sleep(0.1)
            except Exception as e:
                print(f"base 이동 에러: {e}")
                
    def changeToPanTilt(self, x, y):
        outputPan = -(2*self.xMax - x) if x >= self.xMax else x
        if self.yMax < 0:
            ouputTilt = -y if y < -self.yMax else self.yMax
        else : 
            ouputTilt = y if y < self.yMax else self.yMax
        return outputPan, ouputTilt
    
    def normalizePointInBaseRect(self, pos, targetRect):
        normalizedX = (pos[0] / 1920 * 2) - 1
        normalizedY = ((1080 - pos[1]) / 1080 * 2) - 1
        print(targetRect)
        pan, tilt = 0, 0
        for i, point in enumerate(targetRect):
            for j, coordinate in enumerate(point):
                mapper = (1 - normalizedX) * (1 - normalizedY) / 4 if i == 0 \
                else (1 + normalizedX) * (1 - normalizedY) / 4 if i == 1 \
                else (1 + normalizedX) * (1 + normalizedY) / 4 if i == 2 \
                else (1 - normalizedX) * (1 + normalizedY) / 4
                
                if not j:
                    pan += coordinate * mapper 
                else:
                    tilt += coordinate * mapper
                    
        return pan, tilt
