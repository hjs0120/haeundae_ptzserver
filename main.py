from torch.multiprocessing import Process, Queue
import os 
from store.cctvStore import DetectCCTVStore, PtzCCTVStore, DetectCCTV, PtzCCTV
from store.configStore import ConfigStore, ServerConfig
from store.groupConfigStore import GroupStore
from store.configSettingStore import ConfigSettingStore

from videoProcess.sharedData import SharedDetectData, SharedPtzData
from videoProcess.videoProcess import video
from videoProcess.saveVideo import SaveVideo

from api.ptzServer import PtzVideoServer
from module.ptz import Ptz
import requests
import websockets
import asyncio
import gc
import time

import logging
import logging.config
import json
from ptz_mqtt import subscriber_loop
import signal, sys

from config import CONFIG


# from config import BACKEND_HOST

def setup_logging(
    default_path="logger.json",
    default_level=logging.INFO,
    env_key="LOG_CFG"
):
    """logger.json 설정을 불러와 logging 초기화"""
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value

    if os.path.exists(path):
        with open(path, "rt", encoding="utf-8") as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

class PtzServer():
    def __init__(self, BACKEND_HOST = "192.168.0.31:7000"):
        self.BACKEND_HOST = BACKEND_HOST
        self.ONVIF_PORT = 80
        self.ptzCCTVStore = PtzCCTVStore(self.BACKEND_HOST)
        self.configStore = ConfigStore(self.BACKEND_HOST)
        self.groupStore = GroupStore(self.BACKEND_HOST)
        self.configSettingStore = ConfigSettingStore(self.BACKEND_HOST)
        
        self.getDataLoad()

        self.ptz_event_queues = {}
        self.ptz_mqtt = None
        
    def getDataLoad(self):
        self.ptzCCTVStore.getData()
        self.configStore.getData()
        self.groupStore.getData()

        self.configSettingStore.getData()
        
        self.ptzCCTV = self.ptzCCTVStore.ptzCCTV
        self.config = self.configStore.config
        self.group = self.groupStore.group

        self.configSetting = self.configSettingStore.configSettings
        
    def selectServerConfig(self) -> ServerConfig:
        logger.info("서버 설정을 선택해 주세요")
        
        
        userInput = CONFIG["SERVER_INDEX"]
        try:
            inputServerIndex = int(userInput) - 1
        except :
            logger.error("잘못된 입력 입니다, 다시입력해 주세요")

        
        index = self.config[inputServerIndex].index
        ptzPortList = self.config[inputServerIndex].ptzPortList
        wsIndex = self.config[inputServerIndex].wsIndex
        logger.info(f"{index}번 서버 : \n - PTZ 영상 포트 : {ptzPortList} \n - 포트별 영상 갯수 : {wsIndex}")
        
        return self.config[inputServerIndex]
        
    def _filter_by_server_idx(self, cams, server_idx: int):
        """videoServerIdx == server_idx 인 카메라만 반환 (없거나 None이면 제외)"""
        out = []
        for c in cams:
            try:
                v = getattr(c, "videoServerIdx", None)
                # 문자열로 올 수도 있으니 안전 변환
                if v is not None:
                    try: v = int(v)
                    except: pass
                if v == server_idx:
                    out.append(c)
            except Exception:
                pass
        return out

    def _build_matched_for_selected_server(self, selectedConfig, server_idx: int):
        """
        선택된 서버 설정(selectedConfig)에 대해:
        - 전체 리스트에서 videoServerIdx == server_idx 인 것만 추려
        - selectedConfig.detectPortList / ptzPortList × wsIndex 로 슬롯 매핑
        - setProcess에 바로 전달 가능한 dict를 반환
        """
        #detects = self._filter_by_server_idx(self.detectCCTV, server_idx)
        ptzs    = self._filter_by_server_idx(self.ptzCCTV,    server_idx)

        # (선택) 안정된 순서 보장을 원하면 index 기준 정렬
        try:
            #detects.sort(key=lambda x: (x.index is None, x.index))
            ptzs.sort(key=lambda x: (x.index is None, x.index))
        except Exception:
            pass

        #matched_detect = {}
        matched_ptz    = {}

        '''
        # Detect 슬롯 채우기
        d_cur = 0
        for port in selectedConfig.detectPortList:
            bucket = []
            for _ in range(selectedConfig.wsIndex):
                if d_cur < len(detects):
                    bucket.append(detects[d_cur])
                    d_cur += 1
                else:
                    bucket.append(DetectCCTV())  # 빈 슬롯 패딩
            matched_detect[port] = bucket
        '''

        # PTZ 슬롯 채우기
        p_cur = 0
        for port in selectedConfig.ptzPortList:
            bucket = []
            for _ in range(selectedConfig.wsIndex):
                if p_cur < len(ptzs):
                    bucket.append(ptzs[p_cur])
                    p_cur += 1
                else:
                    bucket.append(PtzCCTV())     # 빈 슬롯 패딩
            matched_ptz[port] = bucket

        #return {"detect": matched_detect, "ptz": matched_ptz}
        return {"ptz": matched_ptz}
  

    def updateWsIndex(self):
        
        for cctvType, cctvData in self.compareWsIndex.items():
            if cctvType == "ptz":
                for ptzCCTV, wsUrl in cctvData.items():
                    if ptzCCTV.wsUrl != wsUrl:
                        try:
                            response = requests.get(f"http://{self.BACKEND_HOST}/forVideoServer/setPtzWsIndex?cctvIndex={ptzCCTV.index}&ip={wsUrl['ip']}&port={wsUrl['port']}&index={wsUrl['index']}")
                            if response.status_code == 200 :
                                logger.info("setPtzWsIndex Success")
                            else :
                                logger.error("setPtzWsIndex Fail")
                        except Exception as e :
                            logger.error("setPtzWsIndex Fail : ", e)

            else:
                pass
              
    def main(self):

        selectedConfig = self.selectServerConfig()
        server_idx = int(CONFIG["SERVER_INDEX"])  # 환경/CONFIG에서 사용하던 값
        selectedMatchedServer = self._build_matched_for_selected_server(selectedConfig, server_idx)
        self.setProcess(selectedMatchedServer, selectedConfig)

        self.updateWsIndex()
        self.runProcess()
        
        while True:
            # userinput = input()    
            # if userinput == "q":
            #     break
            time.sleep(1)
            
        # self.killProcess()
        
    def setProcess(self, selectedMatchedServer: dict[str, dict[int, list]], selectedConfig: ServerConfig):
        selectedSetting = next((configSetting for configSetting in self.configSetting if configSetting.index == selectedConfig.index), None)
        #broadcasts: dict[Broadcast, list[int]] = {}
        #self.compareWsIndex:dict[str, dict[DetectCCTV, dict]] = {}

        self.compareWsIndex: dict[str, dict] = {}
        

        maxIndex = 0
        for typeFlag, MatchedServerData in selectedMatchedServer.items():
            if typeFlag == 'detect':
                for detectCCTVs in MatchedServerData.values():
                    for detecCCTV in detectCCTVs:
                        idx = getattr(detecCCTV, "index", None)
                        if isinstance(idx, int) and idx > maxIndex:
                            maxIndex = idx
        maxIndex += 1    
        

        self.ptzVideoServers:list[PtzVideoServer] = []
        self.ptzVideoProcess:list[Process] = []
        self.ptzAutoControlProcs: list[Process] = []
        
        for typeFlag, MatchedServerData in selectedMatchedServer.items():
            if typeFlag == 'ptz':
                self.ptzs: dict[Ptz, bool] = {}
                self.compareWsIndex["ptz"] = {}
                
                for port, ptzCCTVs in MatchedServerData.items():
                    sharedPtzDataList: list[SharedPtzData] = []
                    
                    for i, ptzCCTV in enumerate(ptzCCTVs):
                        # 채널별 이벤트 큐 준비
                        if ptzCCTV.index not in self.ptz_event_queues:
                            self.ptz_event_queues[ptzCCTV.index] = Queue(maxsize=100)

                        sharedPtzData = SharedPtzData()
                        sharedPtzDataList.append(sharedPtzData)
                        # Detect와의 연결/공유데이터는 사용하지 않음 → 빈 리스트 전달
                        sharedDetectDataListForPtz: list[SharedDetectData] = []
                        detectCCTVListForPtz: list = []

                        ptz = Ptz(ptzCCTV, self.ONVIF_PORT, sharedDetectDataListForPtz, detectCCTVListForPtz)
                        #ptzAvailable = ptz.connect()
                        ptzAvailable = False
                        self.ptzs[ptz] = ptzAvailable
                        #self.ptzAutoControlProcs.append(Process(target=ptz.AutoControlProc, args=[ptzAvailable], daemon=True))
                        
                        wsUrl = {'ip': selectedConfig.host, 'port': port, 'index': i}
                        self.compareWsIndex["ptz"][ptzCCTV] = wsUrl
                        
                        self.ptzVideoProcess.append(Process(target=video, 
                                                            args=(ptzCCTV, sharedPtzData, self.BACKEND_HOST, selectedConfig, [],
                                                            self.ptz_event_queues.get(ptzCCTV.index)), 
                                                            daemon=True))
                    
                    self.ptzVideoServers.append(PtzVideoServer(port, sharedPtzDataList, selectedConfig, self.ptzs))
            
        self.serverProcs = [Process(target=ptz_video_server.run, args=(), daemon=True) for ptz_video_server in self.ptzVideoServers]
        # MQTT 서브스크라이버 프로세스 1개 생성
        self.ptz_mqtt = Process(
            target=subscriber_loop,
            args=(self.ptz_event_queues,self.ptzCCTV),
            daemon=True
        )

        
    
    def runProcess(self):
        try:
            if self.ptz_mqtt is not None and not self.ptz_mqtt.is_alive():
                self.ptz_mqtt.start()

            for proc in self.serverProcs + self.ptzVideoProcess + self.ptzAutoControlProcs:
                proc.start()
            asyncio.run(self.sendMessage(f"ws://{self.BACKEND_HOST}", 'reload'))
        except Exception as e:
            logger.error("runProcess error:", e)

    def killProcess(self):
        try:
            for proc in self.serverProcs + self.ptzVideoProcess:
                if proc.is_alive():
                    proc.kill()
                    proc.join()
        except:
            pass
        # MQTT 구독자 종료
        try:
            if self.ptz_mqtt is not None and self.ptz_mqtt.is_alive():
                self.ptz_mqtt.kill()
                self.ptz_mqtt.join()
        except:
            pass

        gc.collect()
        
    async def sendMessage(self, uri, message):
        async with websockets.connect(uri) as websocket:
            await websocket.send(message)
            logger.info(f"Message sent: {message}")
        
if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("서비스 시작")
    logger.debug("디버그 모드 활성화")
    logger.error("에러 발생 예시")
    
    ptzserver = PtzServer(CONFIG["BACKEND_HOST"])

    def _graceful_exit(signum, frame):
        logger.info(f"SIG{signum} received -> shutting down children and exiting")
        try:
            ptzserver.killProcess()  # 자식 프로세스 정리
        except Exception as e:
            logger.error(f"killProcess error: {e!r}")
        sys.exit(0)  # PID1 종료 → 컨테이너 종료(재시작 정책 있으면 재기동)

    signal.signal(signal.SIGTERM, _graceful_exit)
    signal.signal(signal.SIGINT,  _graceful_exit)

    ptzserver.main()
