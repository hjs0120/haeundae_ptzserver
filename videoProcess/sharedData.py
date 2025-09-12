import os
from torch.multiprocessing import Queue, Array, Value
from multiprocessing.sharedctypes import SynchronizedArray, Synchronized
from config import CONFIG

import queue as pyqueue

import time


class SharedDetectData:
    def __init__(self):
        fullFrameSize = CONFIG["fullFrameSize"]

        #self.sharedFullFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fullFrameSize)
        
        self.sharedDetectFlag: Synchronized = Value('b', False)
        self.smsDestinationQueue: Queue = Queue()
        self.eventRegionQueue: Queue = Queue()
        self.ptzCoordsQueue: Queue = Queue()
        self.sensitivityQueue: Queue = Queue()
        self.settingQueue : Queue = Queue()

        
class SharedPtzData:
    def __init__(self):
        #fullFrameSize = CONFIG["fullFrameSize"]
        #self.sharedFullFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fullFrameSize)

        self.fullFrameQ: Queue = Queue(maxsize=2)


    # 큐가 가득 차면 가장 오래된 것 하나 버리고 최신을 넣는다.
    def push_latest_full(self, jpg: bytes) -> None:
        try:
            # 먼저 시도
            self.fullFrameQ.put_nowait(jpg)
            return
        except pyqueue.Full:
            pass

        # 전부 비우기 (가득 차 있으면 모두 버림)
        try:
            while True:
                _ = self.fullFrameQ.get_nowait()
        except pyqueue.Empty:
            pass

        # 최신 한 장만 넣기
        try:
            self.fullFrameQ.put_nowait(jpg)
        except pyqueue.Full:
            # 소비자가 완전히 멈춘 극단상황 – 정책상 무시
            pass   
