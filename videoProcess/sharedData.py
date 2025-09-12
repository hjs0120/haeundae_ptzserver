import os
from torch.multiprocessing import Queue, Array, Value
from multiprocessing.sharedctypes import SynchronizedArray, Synchronized
from config import CONFIG

import queue as pyqueue


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
            self.fullFrameQ.put_nowait(jpg)
        except pyqueue.Full:
            try:
                _ = self.fullFrameQ.get_nowait()
            except pyqueue.Empty:
                pass
            self.fullFrameQ.put_nowait(jpg)