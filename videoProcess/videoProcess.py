from __future__ import annotations
import contextlib
from torch.multiprocessing import Queue

import requests

from av.container import InputContainer
from av import open
from av.video.frame import VideoFrame

import cv2
from cv2 import imencode, resize, INTER_AREA, IMWRITE_JPEG_QUALITY
from cv2.typing import MatLike
import numpy as np
from typing import Deque, Dict

from urllib.parse import quote_plus
from collections import deque
import time

from store.cctvStore import PtzCCTV
from store.configStore import ServerConfig
from videoProcess.sharedData import SharedPtzData
from videoProcess.saveVideo import SaveVideo

import json
import os

import gc
import ctypes

from config import CONFIG

import logging
logger = logging.getLogger(__name__)

# --- AV 리소스 정리 헬퍼 ---
def _release_av(container=None, video_stream=None):
    """잔여 디코드 프레임 flush → close → 참조 해제 → GC → (glibc) 힙 트림"""
    try:
        if container is not None:
            # 1) 디코더 잔여 프레임 비우기
            with contextlib.suppress(Exception):
                if video_stream is not None and hasattr(video_stream, "index"):
                    for _ in container.decode(video=video_stream.index):
                        pass
                else:
                    for _ in container.decode(video=0):
                        pass
            # 2) 컨테이너 닫기
            with contextlib.suppress(Exception):
                container.close()
    finally:
        gc.collect()
        with contextlib.suppress(Exception):
            ctypes.CDLL("libc.so.6").malloc_trim(0)



def video(ptzCCTV: PtzCCTV, sharedPtzData: SharedPtzData, backendHost, serverConfig:ServerConfig, saveVideoList:list[SaveVideo], event_queue: Queue | None):   
    url = ptzCCTV.rtsp
    cctvIndex = ptzCCTV.index

    fullFrameQuality = CONFIG["fullFrameQuality"]


    fps = 15
    maxDuration = 20
    saveBufferSize = int(maxDuration * fps)
    frameBuffer: deque[bytes] = deque(maxlen=saveBufferSize)
    future_needed_sec = 15

    saveVideoFrameCnt = 0
    save_requests: Dict[str, int] = {}  # {out_path: N0}
    saving = False  # 단순 플래그(채널당 동시 저장 1개 제한)

    options={'rtsp_transport': 'tcp',
             'max_delay': '1000',
             'stimeout' : '1000',
             'c:v': 'h264',
             'hwaccel': 'cuda'
             }

    src_type = "rtsp"
    prev_time = None
    fail_count = 0
    fail_threshold = 10 # 연속 실패 10프레임 → 재연결 트리거

    container = None
    videoStream = None

    while url is not None:
        try:
            # URL 형식에 따라 AV open 분기
            try:
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
                    src_type = "rtsp"
                else:
                    # 로컬 파일 또는 HTTP 비디오
                    container: InputContainer = open(
                        url, 'r',
                        options={
                            "probesize": "32768",
                            "analyzeduration": "0",
                            "fflags": "nobuffer"
                        }
                    )
                    src_type = "video"
            except Exception as e:
                logger.error(f"{cctvIndex}번 영상 open 실패: {e}", flush=True)
                time.sleep(3)   # 잠깐 대기 후 재시도
                continue

            
            
            # 비디오 스트림 찾기
            videoStream = next(s for s in container.streams if s.type == 'video')
            videoStream.thread_type = 'AUTO'
            height, width = 1080, 1920

            # 파일일 때만 FPS 추출
            frame_interval = None
            if src_type == "video":
                try:
                    if videoStream.average_rate:
                        video_fps = float(videoStream.average_rate)
                    elif videoStream.guessed_rate:
                        video_fps = float(videoStream.guessed_rate)
                    else:
                        video_fps = None
                    if video_fps and video_fps > 0:
                        frame_interval = 1.0 / video_fps
                except Exception:
                    frame_interval = None
            
            
            prev_time = None

            # ------ demux 루프 (파일 EOF에서는 seek(0)으로 되감기, RTSP는 기존 흐름 유지) ------
            demux_iter = container.demux(videoStream)
            while True:
                packet = next(demux_iter, None)
                if packet is None:
                    if src_type == "video":
                        # EOF → 재오픈 대신 되감기 시도
                        with contextlib.suppress(Exception):
                            videoStream.codec_context.flush()
                        try:
                            container.seek(0, stream=videoStream)
                            demux_iter = container.demux(videoStream)
                            prev_time = None  # 주기 상태 초기화
                            try:
                                frameBuffer.clear()
                            except Exception:
                                pass
                            continue
                        except Exception as _rew:
                            logger.error(f"[PTZ] seek(0) 실패 → 재오픈으로 전환: {_rew}")
                            break  # finally에서 close → 외부 루프가 재오픈
                    else:
                        break
                for frame in packet.decode():
                    
                    t0 = time.time()
                    frame: VideoFrame
                    
                    try:
                        image = frame.to_ndarray(format='bgr24') 
                        #buffer = encode_webp_pillow(image, fullFrameQuality)
                        #if len(buffer) > len(sharedPtzData.sharedFullFrame):
                        #    buffer = buffer[:len(sharedPtzData.sharedFullFrame)]
                        #sharedPtzData.sharedFullFrame[:len(buffer)] = buffer.tobytes()

                        # === BUFFER TO SAVE: numpy(BGR)로만 보관 ===
                        try:
                            if image is None or image.size == 0:
                                raise ValueError("empty frame")
                            if not np.isfinite(image).all():
                                raise ValueError("NaN/Inf in frame")
                            h, w = image.shape[:2]
                            if w <= 0 or h <= 0:
                                raise ValueError(f"bad size {w}x{h}")
                            # 짝수 해상도로 보정(인코딩 호환)
                            tw, th = w - (w % 2), h - (h % 2)
                            if (tw != w) or (th != h):
                                image = cv2.resize(image, (tw, th), interpolation=cv2.INTER_LINEAR)

                            ok, enc = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 65])
                            if ok:
                                # enc: np.ndarray (uint8 1-D). tobytes()는 한 번만 호출해 재사용
                                jpg_bytes = enc.tobytes()

                                # 1) 이벤트 저장용 순환버퍼에 JPEG 바이트 push
                                frameBuffer.append(jpg_bytes)
                                saveVideoFrameCnt += 1

                                # 2) 실시간 공유메모리에도 같은 JPEG 바이트 복사 (초과 방지)
                                dst = sharedPtzData.sharedFullFrame
                                maxlen = len(dst)
                                n = len(jpg_bytes)
                                if n > maxlen:
                                    n = maxlen
                                # 불필요한 복사 줄이기 위해 memoryview 사용
                                dst[:n] = memoryview(jpg_bytes)[:n]
                                # 길이 메타가 있다면 갱신 (없으면 무시)
                                try:
                                    sharedPtzData.sharedFullLen.value = n
                                except Exception:
                                    pass
                            saveVideoFrameCnt += 1
                        except Exception as _buf_e:
                            #print(f"[CH{cctvIndex}] drop bad frame before save: {_buf_e}", flush=True)
                            logger.error(f"[CH{cctvIndex}] drop bad frame before save: {_buf_e}")

                        # 1) 이벤트 큐 폴링 → 저장 요청 등록
                        if event_queue is not None:
                            while True:
                                try:
                                    item = event_queue.get_nowait()
                                except Exception:
                                    break
                                if isinstance(item, dict) and item.get("cmd") == "save":
                                    dt = str(item.get("dateTime", ""))
                                    if not dt:
                                        continue
                                    # 출력 경로: PTZ_SAVE_DIR/{ptzIndex}/ptz_{ptzIndex}_{dateTime}.mp4

                                    safe_name = ptzCCTV.cctvName.replace(" ", "_").replace("#", "")
                                    outdir = f"public/eventPtzVideo/{ptzCCTV.index}"
                                    os.makedirs(outdir, exist_ok=True)
                                    outputPtzVideo = f"{outdir}/{safe_name}_{dt}.mp4"
                                    save_requests[outputPtzVideo] = saveVideoFrameCnt
                                    logger.info(f"[PTZ{cctvIndex}] save request N0={saveVideoFrameCnt} → {outputPtzVideo}")

                        # 2) 저장 조건 충족 시 스냅샷 저장 시작
                        if save_requests and (len(frameBuffer) >= saveBufferSize) and (not saving):
                            done = []
                            for out_path, N0 in save_requests.items():
                                need = N0 + int(future_needed_sec * fps)  # 뒤 15초 확보
                                if saveVideoFrameCnt >= need:
                                    try:
                                        saving = True
                                        snapshot = list(frameBuffer)  # 최근 20초
                                        # 별도 스레드로 저장(캡처 블로킹 방지)
                                        from threading import Thread
                                        saver = saveVideoList[0] if (saveVideoList and len(saveVideoList) > 0) else SaveVideo()
                                        def _save():
                                            try:
                                                # ▶ 변경: JPEG 바이트를 그대로 ffmpeg(image2pipe/mjpeg)로 파이프
                                                if snapshot:
                                                    logger.info(f"[PTZ{cctvIndex}] save start frames={len(snapshot)} fps={int(fps)} → {out_path}")
                                                    saver.save_jpegpipe(snapshot, int(fps), out_path)
                                                    logger.info(f"[PTZ{cctvIndex}] save done → {out_path}")
                                                else:
                                                    logger.warning(f"[PTZ{cctvIndex}] skip save: empty snapshot → {out_path}")
                                            finally:
                                                nonlocal saving
                                                saving = False
                                        Thread(target=_save, daemon=True).start()
                                    except Exception as se:
                                        logger.warning(f"[PTZ{cctvIndex}] save start failed: {se}")
                                        saving = False
                                    finally:
                                        done.append(out_path)
                            for k in done:
                                save_requests.pop(k, None)

                    except Exception as e:
                        # 변환/유효성 실패 → 카운트 증가 후 임계치 검사
                        #print(f"{cctvIndex}번 CCTV: 프레임 변환 실패 → {e}", flush=True)
                        fail_count += 1
                        if fail_count >= fail_threshold:
                            # 상위 try/except에서 container.close() 및 재연결 처리
                            raise
                        continue
                        
                    # === 슬립 (단순화 버전) ===
                    t1 = time.time()
                    proc_dt = t1 - t0

                    if src_type == "video":
                        if frame_interval:
                            # 목표 간격 - 처리시간 만큼만 쉼 (1배속)
                            sleep_s = frame_interval - proc_dt
                            if sleep_s > 0:
                                time.sleep(sleep_s)
                    else:  # RTSP
                        now = t1
                        if prev_time is not None:
                            dt = now - prev_time  # 이전 프레임부터 현재 프레임까지 실제 간격
                            # 이미 dt만큼 시간이 지나 있음 → 처리시간을 빼고 남은 만큼만 살짝 쉼
                            # (RTSP는 원래 실시간이므로 과도한 슬립은 피하고 상한을 둠)
                            remain = dt - proc_dt
                            if remain > 0:
                                time.sleep(min(remain, 0.05))
                        prev_time = now

        except Exception as e :
            try:
                logger.error(f'{cctvIndex}번 영상 재생 에러 : {e}')
                if hasattr(container, 'close'):
                    container.close()
                    _release_av(container, videoStream)
            except Exception as e:
                logger.error(f'container 조회 실패 : {e}')            
            try:
                logMessage = f"{cctvIndex}번 PTZ 영상 재생 에러"
                encodedLogMessage = quote_plus(logMessage)
                setLogUrl = f"http://{backendHost}/forVideoServer/setVideoServerLog?videoServerIndex={serverConfig.index}&logMessage={encodedLogMessage}"
                res = requests.get(setLogUrl, timeout=5)
                if res.status_code == 200:
                    logger.error(res.text)
            except Exception as logErr : 
                logger.error(f"에러로그 입력 실패: {logErr}")

        finally:
            time.sleep(3)
            try: 
                if hasattr(container, 'close'):
                    container.close()
                else:
                    logger.error("컨테이너 클로즈 실패: 컨테이너 객체가 존재하지 않음.")
                _release_av(container, videoStream)
            except Exception as e:
                logger.error(f'container 조회 실패 : {e}')
    
    
def resizeImage(image:MatLike, width = 320, height = 206):
    dimension = (width, height)
    return resize(image, dimension, interpolation=INTER_AREA)

def encode_webp_pillow(image, quality=75):
    return imencode('.jpg', image, [IMWRITE_JPEG_QUALITY, quality])[1]
    
    
    




