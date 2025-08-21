CONFIG = {
    "SERVER_INDEX": 1,
    "BACKEND_HOST": "192.168.0.3:7000",

    # Sizes
    "MINI_SIZE": [480, 338],
    "MEDIUM_SIZE": [960, 560],
    "fullFrameSize": 300000,
    "fourthSplitSize": 75000,
    "thirtySplitSize": 10000,

    # Qualities
    "fullFrameQuality": 65,
    "fourthSplitQuality": 35,
    "thirtySplitQuality": 15,

    # Etc
    "maxObjectHeight": 108,

    # MQTT 설정
    "MQTT_BROKER": "192.168.0.180",
    "MQTT_PORT": 1883,
    "MQTT_TOPIC": "detect/events",   # 디텍트서버가 publish한 토픽 베이스
    "CLIENT_ID": "ptz-server", 
    "MQTT_USERNAME": "kiot",
    "MQTT_PASSWORD": "kiot!@34",   

    # --- PTZ 맵핑: [1,2] → PTZ 1번, [3,4] → PTZ 2번 ...
    "LINKED_CCTV_GROUPS": [[1,2],[3,4],[5,6],[7,8],[9,10],[11,12],[13,14],[15,16],[17,18],[19,20]],


}