from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from fastapi.responses import HTMLResponse, Response
from hypercorn.config import Config
from hypercorn.asyncio import serve
import asyncio
import json
from module.ptz import Ptz
from store.configStore import ServerConfig
from videoProcess.videoProcess import SharedPtzData
from fastapi.staticfiles import StaticFiles

import time

import logging
logger = logging.getLogger(__name__)

class PtzVideoServer():
    def __init__(self, port, sharedPtzDataList: list[SharedPtzData], serverConfig: ServerConfig, ptzs:dict[Ptz, bool]):
        super(PtzVideoServer, self).__init__()
        
        self.serverPort = port
        self.serverConfig = serverConfig
        
        self.app = FastAPI()
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"], 
            allow_headers=["*"], 
        )

        self.app.mount("/public", StaticFiles(directory="public"), name="public")
        
        @self.app.get("/")
        async def main():
            return {"message": "Welcome to PtzVideoServer!"}

          
        streamClient = [[] for index in range(serverConfig.wsIndex)]
        
        async def _send_full_once(websocket, sharedPtzDataList, index: int):
            sd = sharedPtzDataList[index]
            full_len = getattr(sd, "sharedFullLen", None)
            if isinstance(full_len, int) and full_len > 0:
                await websocket.send_bytes(bytes(sd.sharedFullFrame[:full_len]))
            else:
                await websocket.send_bytes(bytes(sd.sharedFullFrame[:]))  # 길이 메타 없으면 전체
        
        def _is_ready(sd) -> bool:
            full_len = getattr(sd, "sharedFullLen", None)
            if isinstance(full_len, int):
                return full_len > 0
            try:
                buf = getattr(sd, "sharedFullFrame", None)
                return buf is not None and len(bytes(buf[:])) > 0
            except Exception:
                return False

        async def _wait_first_frame(sharedPtzDataList, index, timeout=3.0):
            t0 = time.monotonic()
            while time.monotonic() - t0 < timeout:
                try:
                    sd = sharedPtzDataList[index]
                except Exception:
                    await asyncio.sleep(0.05); continue
                if _is_ready(sd):
                    return True
                await asyncio.sleep(0.05)
            return False

        @self.app.websocket("/ws/stream/{index}")
        async def websocketStream(websocket: WebSocket, index):
            """
            detect 서버와 동일한 흐름:
            - accept → append → 단일 루프(전송 + 명령 폴링)
            - 어떤 종료 경로든 finally에서 close/remove 보장
            - 끊김 계열 예외는 조용히 종료
            """
            from starlette.websockets import WebSocketDisconnect, WebSocketState
            import anyio, time

            index = int(index)
            await websocket.accept()
            streamClient[index].append(websocket)
            logger.info(f'{port}/{index}: accept, clients={len(streamClient[index])}')

            # 초기 FPS (필요 시 설정/ENV에서 읽어오세요)
            fps_current = 10
            interval = 1.0 / max(1, fps_current)
            last_sent = 0.0

            try:
                # 1) 첫 명령 1회 수신(옵션)
                try:
                    first_cmd = await websocket.receive_text()
                    logger.debug(f'{port}/{index}: first_cmd="{first_cmd}"')
                    if first_cmd.strip().lower() == "stop":
                        return  # finally에서 정리
                    if first_cmd.startswith("fps="):
                        val = first_cmd.split("=",1)[1].strip()
                        try:
                            fps_current = max(1, int(val))
                            interval = 1.0 / fps_current
                            logger.info(f'{port}/{index}: set fps -> {fps_current}')
                        except Exception:
                            logger.warning(f'{port}/{index}: bad fps "{first_cmd}"')
                except WebSocketDisconnect:
                    return
                except Exception as e:
                    logger.debug(f'{port}/{index}: first_cmd read skip: {e}')

                # 2) 단일 루프: 전송 + 명령 폴링
                while websocket.client_state == WebSocketState.CONNECTED:
                    try:
                        now = time.monotonic()
                        # 남은 시간 동안만 명령 폴링(논블로킹)
                        remaining = max(0.0, (last_sent + interval) - now)
                        if remaining > 0:
                            try:
                                with anyio.move_on_after(min(remaining, 0.05)):
                                    cmd = await websocket.receive_text()
                                    if cmd.startswith("fps="):
                                        val = cmd.split("=",1)[1].strip()
                                        try:
                                            fps_current = max(1, int(val))
                                            interval = 1.0 / fps_current
                                            logger.info(f'{port}/{index}: set fps -> {fps_current}')
                                        except Exception:
                                            logger.warning(f'{port}/{index}: bad fps "{cmd}"')
                                    elif cmd.strip().lower() == "stop":
                                        break
                            except WebSocketDisconnect:
                                break
                            except Exception:
                                pass  # 폴링 에러는 무시

                        # 전송 타이밍 도달 시 프레임 전송
                        if time.monotonic() - last_sent >= interval:
                            try:
                                # ★ 전송 함수는 기존 구현 이름에 맞게 사용
                                await _send_full_once(websocket, sharedPtzDataList, index)
                                last_sent = time.monotonic()
                            except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError, anyio.EndOfStream):
                                break  # 끊김은 조용히 종료
                            except Exception as send_e:
                                logger.error(f'{port}/{index}: send error: {send_e}')
                                break

                    except WebSocketDisconnect:
                        break
                    except Exception as loop_e:
                        logger.error(f'{port}/{index}: loop error: {loop_e}')
                        break

            finally:
                # 어떤 경로로든 항상 정리
                try:
                    await websocket.close()
                except Exception:
                    pass
                try:
                    if websocket in streamClient[index]:
                        streamClient[index].remove(websocket)
                except Exception:
                    pass
                logger.info(f'{port}/{index}: close, clients={len(streamClient[index])}')

        '''
        @self.app.websocket("/ws/stream/{index}")
        async def websocketStream(websocket: WebSocket, index):
            index = int(index)
            await websocket.accept()
            streamClient[index].append(websocket)
            logger.info(f'{port}/{index}: accept, clients={len(streamClient[index])}')

            # 0) 기본 FPS로 즉시 시작 (환경변수 DEFAULT_STREAM_FPS 허용; 없으면 10)
            
            fps = 2.0
            fps = max(1.0, min(60.0, fps))
            interval = 1.0 / fps
            # 첫 루프에서 바로 전송되도록 last_sent를 interval만큼 과거로 설정
            last_sent = time.monotonic()

            # 시작 즉시 ACK
            #await websocket.send_text(f"fps={int(fps)}")
            #print(f'{port}/{index}: start fps={fps}')
            
            paused  = False

            # 1) 전송/수신 단일 루프
            while websocket.client_state == WebSocketState.CONNECTED:
                try:
                    if paused:
                        # ⏸ 일시정지 상태: 전송 스케줄링 없음, 다음 명령만 대기
                        try:
                            cmd = await websocket.receive_text()  # timeout 없음
                        except WebSocketDisconnect:
                            break

                        t = (cmd or "").strip().lower()
                        if t == "stop":
                            await websocket.close()
                            if websocket in streamClient[index]:
                                streamClient[index].remove(websocket)
                            logger.info(f'{port}/{index}: stop by client')
                            break

                        # 숫자면 FPS 변경 / 재개
                        try:
                            new_fps = float(t)
                            if new_fps <= 0.0:
                                # 이미 paused이므로 그대로 유지 (ACK만 반환)
                                await websocket.send_text("fps=0 (paused)")
                                continue
                            # 재개
                            fps = min(60.0, max(1.0, new_fps))
                            interval = 1.0 / fps
                            paused = False
                            await websocket.send_text(f"fps={int(fps)}")
                            # 즉시 새 FPS 반영: 다음 전송을 바로 하도록 last_sent 조정
                            last_sent = time.monotonic() - interval
                            logger.info(f'{port}/{index}: resume, fps -> {fps}')
                            continue
                        except ValueError:
                            # 기타 텍스트 명령 무시
                            continue

                    else:
                        # ▶ 송신 중 상태: 타임아웃 동안만 명령 대기, 만료되면 프레임 전송
                        now = time.monotonic()
                        remaining = max(0.0, (last_sent + interval) - now)

                        try:
                            cmd = await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
                        except asyncio.TimeoutError:
                            cmd = None

                        if cmd is not None:
                            t = (cmd or "").strip().lower()
                            if t == "stop":
                                await websocket.close()
                                if websocket in streamClient[index]:
                                    streamClient[index].remove(websocket)
                                logger.info(f'{port}/{index}: stop by client')
                                break
                            else:
                                # 숫자면 FPS 변경 또는 일시정지
                                try:
                                    new_fps = float(t)
                                    if new_fps <= 0.0:
                                        paused = True
                                        await websocket.send_text("fps=0 (paused)")
                                        logger.info(f'{port}/{index}: paused')
                                        # 일시정지 들어가면 다음 루프에서 paused 블록으로
                                        continue
                                    new_fps = min(60.0, max(1.0, new_fps))
                                    if abs(new_fps - fps) > 1e-6:
                                        fps = new_fps
                                        interval = 1.0 / fps
                                        await websocket.send_text(f"fps={int(fps)}")
                                        logger.info(f'{port}/{index}: fps -> {fps}')
                                        # 즉시 반영: 다음 전송 타이밍을 당겨서 곧바로 전송 가능
                                        last_sent = time.monotonic() - interval
                                except ValueError:
                                    pass
                            continue  # 명령 처리 끝, 다음 루프로

                        # 여기까지 왔으면 remaining 만료 → 전송 시점
                        try:
                            await _send_full_once(websocket, sharedPtzDataList, index)
                            last_sent = time.monotonic()
                        except WebSocketDisconnect:
                            break
                        except Exception as e:
                            # 필요 시 로깅/에러 카운팅 후 재시도/연결정책
                            logger.error(f'{port}/{index}: send error: {e}')
                            # 에러 정책에 따라 continue/break
                            continue

                except WebSocketDisconnect:
                    try: await websocket.close()
                    finally:
                        if websocket in streamClient[index]: streamClient[index].remove(websocket)
                    logger.error(f'{port}/{index}: close, clients={len(streamClient[index])}')
                except Exception as e:
                    try: await websocket.close()
                    finally:
                        if websocket in streamClient[index]: streamClient[index].remove(websocket)
                    logger.error(f'{port}/{index}: stream err -> {e!r}, clients={len(streamClient[index])}')
        '''
        
        
    def run(self):
        config = Config()
        config.bind = f'0.0.0.0:{self.serverPort}'
        try:
            asyncio.run(serve(self.app, config))
        except Exception as e:
            print(f'{self.serverPort}serve 에러 : {e}')