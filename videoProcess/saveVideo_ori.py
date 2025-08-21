from threading import Thread
from collections import deque
from fractions import Fraction
from av.video.frame import VideoFrame
from torch.multiprocessing import Process, Queue
from av import open
import gc

class SaveVideo():
    def __init__(self):
        self.saveEventQueue: Queue = Queue()
        self.wrongDetectionQueue: Queue = Queue()
    
    def saveVideo(self, frameBuffer, fps, outputVideo):
        saveVideoThread = Thread(target=self.saveVideoThread, args=(frameBuffer, fps, outputVideo))
        saveVideoThread.start()
        
    def saveVideoThread(self, frameBuffer: deque[VideoFrame], fps, outputVideo):
        frameBufferCopy = frameBuffer.copy() 
        container = open(outputVideo, mode='w')
        stream = container.add_stream('h264', rate=fps)
        stream.width = frameBufferCopy[0].width
        stream.height = frameBufferCopy[0].height

        for i, frame in enumerate(frameBufferCopy):
            if frame.format.name != 'yuv420p':
                frame = frame.reformat(format='yuv420p')
            frame.pts = i
            frame.dts = i
            frame.time_base = Fraction(1, fps)
            encoded_packets = stream.encode(frame)
            for packet in encoded_packets:
                container.mux(packet)
            if i % 50 == 0:  # 50프레임마다 한 번씩
                gc.collect()

        final_encoded_packets = stream.encode(None)
        for packet in final_encoded_packets:
            container.mux(packet)

        container.close()