import os
from torch.multiprocessing import Queue, Array, Value
from multiprocessing.sharedctypes import SynchronizedArray, Synchronized

class SharedDetectData:
    def __init__(self):
        fullFrameSize = int(os.environ["fullFrameSize"])
        fourthSplitSize = int(os.environ["fourthSplitSize"])
        thirtySplitSize = int(os.environ["thirtySplitSize"])

        self.sharedFullFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fullFrameSize)
        self.sharedMediumFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fourthSplitSize)
        self.sharedMiniFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=thirtySplitSize)
        
        self.sharedDetectFlag: Synchronized = Value('b', False)
        self.smsDestinationQueue: Queue = Queue()
        self.eventRegionQueue: Queue = Queue()
        self.ptzCoordsQueue: Queue = Queue()
        self.sensitivityQueue: Queue = Queue()
        self.settingQueue : Queue = Queue()

        
class SharedPtzData:
    def __init__(self):
        fullFrameSize = int(os.environ["fullFrameSize"])
        fourthSplitSize = int(os.environ["fourthSplitSize"])
        thirtySplitSize = int(os.environ["thirtySplitSize"])

        self.sharedFullFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fullFrameSize)
        self.sharedMediumFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=fourthSplitSize)
        self.sharedMiniFrame: SynchronizedArray = Array(typecode_or_type='c', size_or_initializer=thirtySplitSize)
        