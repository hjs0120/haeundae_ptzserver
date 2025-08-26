CONFIG = {
    "SERVER_INDEX": 1,
    "BACKEND_HOST": "192.168.0.3:7000",

    # Sizes
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


}