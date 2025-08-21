# ptz_mqtt.py
from __future__ import annotations
import json
import logging
from typing import Dict, Any

import paho.mqtt.client as mqtt
from config import CONFIG

log = logging.getLogger(__name__)


def cctv_to_ptz_index(cctv_idx: int) -> int:
    """
    LINKED_CCTV_GROUPS = [[1,2],[3,4],...] 라면,
    1,2 → PTZ 1번 / 3,4 → PTZ 2번 매핑.
    못 찾으면 동일 인덱스로 폴백.
    """
    groups = CONFIG.get("LINKED_CCTV_GROUPS", [])
    for i, group in enumerate(groups, start=1):
        if cctv_idx in group:
            return i
    return cctv_idx


def subscriber_loop(ptz_queue_map: Dict[int, Any]):
    """
    단일 MQTT 클라이언트가 메시지를 받아 PTZ 채널별 큐로 라우팅.
    - 기대 payload 예:
      {
        "cctvIndex": 3,
        "objectCoord": [[x,y], ...],
        "savedImageDir": "http://.../image.jpg" | null,
        "savedVideoDir": "http://.../detect.mp4",
        "dateTime": "YYYYmmdd_HHMMSS"   # 파일명 끝에 붙일 값(필수)
      }
    """
    host = CONFIG.get("MQTT_BROKER", "127.0.0.1")
    port = int(CONFIG.get("MQTT_PORT", 1883))
    topic_base = CONFIG.get("MQTT_TOPIC", "detect/events").rstrip("/")
    client_id = CONFIG.get("CLIENT_ID", "ptz-subscriber")
    username = CONFIG.get("MQTT_USERNAME") or None
    password = CONFIG.get("MQTT_PASSWORD") or None

    cli = mqtt.Client(client_id=client_id, clean_session=True)
    if username:
        cli.username_pw_set(username, password)

    def on_connect(c, u, f, rc):
        log.info(f"[MQTT] connected rc={rc} {host}:{port}")
        sub = f"{topic_base}/#"
        c.subscribe(sub, qos=0)
        log.info(f"[MQTT] subscribe: {sub}")

    def on_message(c, u, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            log.warning(f"[MQTT] bad json: {e}")
            return

        cctv_idx = int(payload.get("cctvIndex", -1))
        dateTime = str(payload.get("dateTime", ""))  # 파일명 태그(필수)

        if cctv_idx < 0 or not dateTime:
            log.warning(f"[MQTT] missing cctvIndex/dateTime: keys={list(payload.keys())}")
            return

        ptz_idx = cctv_to_ptz_index(cctv_idx)
        q = ptz_queue_map.get(ptz_idx)
        if q is None:
            log.warning(f"[MQTT] no event queue for PTZ {ptz_idx} (from CCTV {cctv_idx})")
            return

        # 채널 워커로 저장 요청 전달 (비차단)
        try:
            q.put_nowait({"cmd": "save", "dateTime": dateTime})
            log.info(f"[MQTT] save → PTZ{ptz_idx} (from CCTV {cctv_idx}, dt={dateTime})")
        except Exception as e:
            log.warning(f"[MQTT] queue put fail PTZ{ptz_idx}: {e}")

    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.on_disconnect = lambda c, u, rc: log.info(f"[MQTT] disconnected rc={rc}")

    # 별도 프로세스로 기동한다면 loop_forever가 간단
    cli.connect(host, port, keepalive=60)
    cli.loop_forever()
