# saveVideo.py
from threading import Thread
from typing import List, Tuple
import os
import time
import traceback
import contextlib
import unicodedata

import cv2
import numpy as np

import logging
logger = logging.getLogger(__name__)


def ascii_safe_name(filename: str) -> str:
    """
    주어진 파일명(확장자 포함)에서 베이스 이름을 ASCII로 정규화.
    - 한글/특수문자 제거 → 영문/숫자만 남김
    - 베이스 이름이 비면 'video' 사용
    - 확장자는 호출부에서 결정
    """
    base = os.path.basename(filename)
    name, _ext = os.path.splitext(base)
    safe = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return safe or "video"

class SaveVideo:
    """
    저장 파이프라인:
      1) numpy(BGR) 프레임 리스트와 fps, 출력 경로(원래 파일명; 한글 포함 가능)를 받음
      2) 같은 디렉터리에 ASCII-only 임시 파일명으로 저장 시도
         - mp4v(.mp4) → 실패 시 avc1(.mp4) → 실패 시 XVID(.avi)
      3) 성공한 임시 파일을 원래 경로(한글 이름)로 os.replace
    """

    def __init__(self):
        # 기존 인터페이스 호환용
        self.wrongDetectionQueue = None

    def save_numpy(self, frames: List[np.ndarray], fps: int, output_path: str) -> None:
        t = Thread(target=self._save_numpy_thread, args=(frames, fps, output_path), daemon=True)
        t.start()

    def save_jpeg_bytes(self, frames_bytes: list[bytes], fps: int, output_path: str):
        # 첫 프레임 디코드로 해상도 획득
        import numpy as np, cv2, os
        if not frames_bytes:
            return
        first = cv2.imdecode(np.frombuffer(frames_bytes[0], np.uint8), cv2.IMREAD_COLOR)
        h, w = first.shape[:2]

        # VideoWriter 열고 순서대로 디코드→write
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 또는 'avc1'
        tmp_dst = os.path.join(os.path.dirname(output_path) or ".", "tmp_"+os.path.basename(output_path)+".mp4")
        vw = cv2.VideoWriter(tmp_dst, fourcc, fps, (w, h))
        wrote = 0
        for b in frames_bytes:
            img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
            if img is None: continue
            vw.write(img); wrote += 1
        vw.release()
        os.replace(tmp_dst, output_path)

    # ===== 내부 구현 =====
    def _save_numpy_thread(self, frames: List[np.ndarray], fps: int, output_path: str) -> None:
        start_ts = time.time()
        #print(f"[SaveVideo] start → {output_path}", flush=True)
        logger.info(f"[SaveVideo] start → {output_path}")

        # 0) 입력 가드
        if not frames:
            #print(f"[SaveVideo] skip(empty) → {output_path}", flush=True)
            logger.warning(f"[SaveVideo] skip(empty) → {output_path}")
            return

        try:
            # 1) 출력 디렉터리 보장 & 권한 체크
            outdir = os.path.dirname(output_path) or "."
            os.makedirs(outdir, exist_ok=True)
            if not os.access(outdir, os.W_OK):
                #print(f"[SaveVideo] WARN: no write permission to dir: {outdir}", flush=True)
                logger.warning(f"[SaveVideo] WARN: no write permission to dir: {outdir}")

            # 2) 기준 해상도(짝수 보정)
            h, w = frames[0].shape[:2]
            w -= (w % 2)
            h -= (h % 2)
            if w <= 0 or h <= 0:
                raise RuntimeError(f"invalid size {w}x{h}")

            # 3) ASCII-safe 임시 파일명 구성 (같은 디렉터리)
            orig_ext = os.path.splitext(output_path)[1].lower()
            safe_base = ascii_safe_name(output_path)

            # 시도 후보 (파일경로, fourcc, 확장자)
            # mp4 우선, 안 되면 avi로
            attempts: List[Tuple[str, str, str]] = [
                (os.path.join(outdir, f"{safe_base}.mp4"), "mp4v", ".mp4"),
                (os.path.join(outdir, f"{safe_base}.mp4"), "avc1", ".mp4"),
                (os.path.join(outdir, f"{safe_base}.avi"), "XVID", ".avi"),
            ]

            opened_path = None
            opened_fourcc = None
            vw = None
            tried_msgs = []

            # 4) 순차 시도
            for trial_path, fourcc_name, ext in attempts:
                # 같은 이름의 잔여 임시파일이 남아있다면 제거 시도
                with contextlib.suppress(Exception):
                    if os.path.exists(trial_path):
                        os.remove(trial_path)

                try:
                    fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
                    vw = cv2.VideoWriter(trial_path, fourcc, float(fps), (w, h))
                    if vw.isOpened():
                        opened_path = trial_path
                        opened_fourcc = fourcc_name
                        #print(f"[SaveVideo] writer opened: {fourcc_name} → {trial_path}", flush=True)
                        logger.info(f"[SaveVideo] writer opened: {fourcc_name} → {trial_path}")
                        break
                    else:
                        tried_msgs.append(f"{fourcc_name}@{trial_path} (isOpened=False)")
                        try:
                            vw.release()
                        except Exception:
                            pass
                        vw = None
                except Exception as oe:
                    tried_msgs.append(f"{fourcc_name}@{trial_path} ({oe})")
                    vw = None

            if vw is None or opened_path is None:
                raise RuntimeError("VideoWriter open failed; tried: " + " | ".join(tried_msgs))

            # 5) 프레임 기록
            wrote = 0
            for i, img in enumerate(frames):
                if img is None or img.size == 0:
                    continue
                ih, iw = img.shape[:2]
                if ih != h or iw != w:
                    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)
                vw.write(img)
                wrote += 1
                #if (i + 1) % 60 == 0:
                #    print(f"[SaveVideo] progress {i+1}/{len(frames)} → {opened_path}", flush=True)

            vw.release()
            if wrote == 0:
                raise RuntimeError("no frames written")

            # 6) 최종 파일명 결정: 원래 확장자 유지 시도, 다만 임시가 .avi면 .avi로 저장
            final_dst = output_path
            if opened_path.endswith(".avi") and not output_path.lower().endswith(".avi"):
                final_dst = os.path.splitext(output_path)[0] + ".avi"

            # 목적지 디렉터리 보장
            os.makedirs(os.path.dirname(final_dst) or ".", exist_ok=True)
            os.replace(opened_path, final_dst)  # ASCII → 원래(한글) 경로로 원자적 이동

            dur = time.time() - start_ts
            #print(f"[SaveVideo] done({wrote} frames, {dur:.2f}s, {opened_fourcc}) → {final_dst}", flush=True)
            logger.info(f"[SaveVideo] done({wrote} frames, {dur:.2f}s, {opened_fourcc}) → {final_dst}")


        except Exception as e:
            #print(f"[SaveVideo] ERROR {output_path}: {e}", flush=True)
            logger.error(f"[SaveVideo] ERROR {output_path}: {e}")
            #traceback.print_exc()
            # 실패 시 임시파일 정리
            with contextlib.suppress(Exception):
                # 우리가 만든 ASCII 후보들 정리
                for ext in (".mp4", ".avi"):
                    p = os.path.join(os.path.dirname(output_path) or ".", f"{ascii_safe_name(output_path)}{ext}")
                    if os.path.exists(p):
                        os.remove(p)
