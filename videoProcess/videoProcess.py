import contextlib
from torch.multiprocessing import Queue
from concurrent.futures import ThreadPoolExecutor

import requests

from av.container import InputContainer
from av import open
from av.video.frame import VideoFrame

from cv2 import imencode, resize, INTER_AREA, IMWRITE_JPEG_QUALITY
from cv2.typing import MatLike

from urllib.parse import quote_plus
from collections import deque
import time

from store.cctvStore import PtzCCTV
from store.configStore import ServerConfig
from videoProcess.sharedData import SharedPtzData
from videoProcess.saveVideo import SaveVideo

import json
import os

# def video(ptzCCTV: PtzCCTV, sharedFullFrames:SynchronizedArray, sharedMiniFrames:SynchronizedArray, backendHost, serverConfig):

def video(ptzCCTV: PtzCCTV, sharedPtzData: SharedPtzData, backendHost, serverConfig:ServerConfig, saveVideoList:list[SaveVideo]):
    
    print("start ptz video func")
    
    executor = ThreadPoolExecutor(max_workers=3)

    url = ptzCCTV.rtsp
    cctvIndex = ptzCCTV.index
    wrongDetectionQueueList:list[Queue] = []
    saveEventQueueList:list[Queue] = []
    saveVideo = saveVideoList[0]

    miniWidth = json.loads(os.environ["MINI_SIZE"])[0]
    miniHeight = json.loads(os.environ["MINI_SIZE"])[1]
    mediumWidth = json.loads(os.environ["MEDIUM_SIZE"])[0]
    mediumHeight = json.loads(os.environ["MEDIUM_SIZE"])[1]
    thirtySplitQuality = int(os.environ["thirtySplitQuality"])
    fourthSplitQuality = int(os.environ["fourthSplitQuality"])
    fullFrameQuality = int(os.environ["fullFrameQuality"])

    for saveVideo in saveVideoList:
        wrongDetectionQueueList.append(saveVideo.wrongDetectionQueue)
        saveEventQueueList.append(saveVideo.saveEventQueue)

    fps = 15
    maxDuration = 20
    saveBufferSize = int(maxDuration * fps)
    frameBuffer: deque[VideoFrame] = deque(maxlen=saveBufferSize)

    options={'rtsp_transport': 'tcp',
             'max_delay': '1000',
             'stimeout' : '1000',
             'c:v': 'h264',
             'hwaccel': 'cuda'
             }

    while url is not None:
        try:
            #container:InputContainer = open(url, 'r', format='rtsp', options=options, buffer_size=102400 * 12, timeout=10)
            #videoStream = next(s for s in container.streams if s.type == 'video')
            #videoStream.thread_type = 'AUTO'
            
            
            # URL 형식에 따라 AV open 분기
            if url.lower().startswith("rtsp://"):
                # RTSP 스트림
                container: InputContainer = open(
                    url,
                    'r',
                    format='rtsp',
                    options=options,
                    buffer_size=102400 * 12,
                    timeout=10
                )
            else:
                # 로컬 파일 또는 HTTP 비디오
                container: InputContainer = open(url, 'r')  # format 지정 안 함
            
            # 비디오 스트림 찾기
            videoStream = next(s for s in container.streams if s.type == 'video')
            videoStream.thread_type = 'AUTO'
            height, width = 1080, 1920
            
            saveVideoFrameCnt:list[int] = [0] * len(saveVideoList)

            saveVideoRequestsList:list[dict[int, str]] = [{}] * len(saveVideoList)
            
            print(f'test point {url}')

            for packet in container.demux(videoStream):
                for frame in packet.decode():
                    frame: VideoFrame
                    image = frame.to_ndarray(format='bgr24') 

                    #for index, saveEventQueue in enumerate(saveEventQueueList):
                    #    with contextlib.suppress(Exception):
                    #        outputVideo = saveEventQueue.get_nowait()
                    #        saveVideoRequestsList[index][outputVideo] = saveVideoFrameCnt[index]
                    #saveFrame = VideoFrame.from_ndarray(image.copy(), format='bgr24')
                    #frameBuffer.append(saveFrame)
                    #if len(frameBuffer) > saveBufferSize:   
                    #    frameBuffer.popleft()

                    #for index, saveVideoRequests in enumerate(saveVideoRequestsList):
                    #    if saveVideoRequests != {}:
                    #        saveVideoFrameCnt[index] += 1
                    #        KeyToDelete = []
                    #        for outputVideo_,  saveVideoRequest in saveVideoRequests.items():
                    #            if saveVideoFrameCnt[index] >= saveVideoRequest + saveBufferSize:
                                    #saveVideo.saveVideo(frameBuffer, fps, outputVideo_)
                                    #print("ptz save")
                    #                KeyToDelete.append(outputVideo_)
                    #        for item in KeyToDelete:
                    #            del saveVideoRequests[item]
                    #        with contextlib.suppress(Exception):
                    #            wrongDetectionDir = wrongDetectionQueueList[index].get_nowait()
                    #            del saveVideoRequests[wrongDetectionDir]
                    #    else:
                    #        saveVideoRequest = 0

                    #miniSizeImage = resizeImage(image, miniWidth, miniHeight)
                    #mediumSizeImage = resizeImage(image, mediumWidth, mediumHeight)


                    #mini_future = executor.submit(encode_webp_pillow, miniSizeImage, thirtySplitQuality)
                    #medium_future = executor.submit(encode_webp_pillow, mediumSizeImage, fourthSplitQuality)
                    full_future = executor.submit(encode_webp_pillow, image, fullFrameQuality)

                    # 결과를 기다림
                    #miniSizeBuffer = mini_future.result()
                    #mediumSizeBuffer = medium_future.result()
                    buffer = full_future.result()

                    #if len(miniSizeBuffer) > len(sharedPtzData.sharedMiniFrame):
                    #    miniSizeBuffer = miniSizeBuffer[:len(sharedPtzData.sharedMiniFrame)]
                    #if len(mediumSizeBuffer) > len(sharedPtzData.sharedMediumFrame):
                    #    mediumSizeBuffer = mediumSizeBuffer[:len(sharedPtzData.sharedMediumFrame)]
                    if len(buffer) > len(sharedPtzData.sharedFullFrame):
                        buffer = buffer[:len(sharedPtzData.sharedFullFrame)]

                    #sharedPtzData.sharedMiniFrame[:len(miniSizeBuffer)] = miniSizeBuffer.tobytes()
                    #sharedPtzData.sharedMediumFrame[:len(mediumSizeBuffer)] = mediumSizeBuffer.tobytes()
                    sharedPtzData.sharedFullFrame[:len(buffer)] = buffer.tobytes()

        except Exception as e :
            try:
                print(f'{cctvIndex}번 영상 재생 에러 : {e}')
                if hasattr(container, 'close'):
                    container.close()
            except Exception as e:
                print(f'container 조회 실패 : {e}')            
            try:
                logMessage = f"{cctvIndex}번 PTZ 영상 재생 에러"
                encodedLogMessage = quote_plus(logMessage)
                setLogUrl = f"http://{backendHost}/forVideoServer/setVideoServerLog?videoServerIndex={serverConfig.index}&logMessage={encodedLogMessage}"
                res = requests.get(setLogUrl)
                if res.status_code == 200:
                    print(res.text)
            except Exception as logErr : 
                print(f"에러로그 입력 실패: {e}")

        finally:
            time.sleep(3)
            try: 
                if hasattr(container, 'close'):
                    container.close()
                else:
                    print("컨테이너 클로즈 실패: 컨테이너 객체가 존재하지 않음.")
            except Exception as e:
                print(f'container 조회 실패 : {e}')
    
    
def resizeImage(image:MatLike, width = 320, height = 206):
    dimension = (width, height)
    return resize(image, dimension, interpolation=INTER_AREA)

def encode_webp_pillow(image, quality=75):
    return imencode('.jpg', image, [IMWRITE_JPEG_QUALITY, quality])[1]
    
    
    




