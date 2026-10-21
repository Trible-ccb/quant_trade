# -*- coding: utf-8 -*-
import struct
import json
import time

SHM_NAME = "QMT_SIGNAL_SHM"
SHM_SIZE = 1024 * 1024  # 1MB
SLOT_SIZE = 4096
MAX_SLOTS = (SHM_SIZE - 16) // SLOT_SIZE

class SharedMemoryQueue:
    def __init__(self, create=False):
        from multiprocessing import shared_memory
        try:
            self.shm = shared_memory.SharedMemory(name=SHM_NAME, create=create, size=SHM_SIZE)
        except FileExistsError:
            self.shm = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        
        if create:
            # 初始化头部索引为0
            struct.pack_into('<QQ', self.shm.buf, 0, 0, 0)
            
    def push(self, data_dict):
        """External process: write signal"""
        w_idx, r_idx = struct.unpack_from('<QQ', self.shm.buf, 0)
        
        if w_idx - r_idx >= MAX_SLOTS:
            print("[SHM] Queue full, dropping signal")
            return False
            
        slot_offset = 16 + (w_idx % MAX_SLOTS) * SLOT_SIZE
        data_bytes = json.dumps(data_dict).encode('utf-8')
        
        if len(data_bytes) > SLOT_SIZE - 4:
            print("[SHM] Signal too large, cannot write")
            return False
            
        # 写入长度和数据
        struct.pack_into('<I', self.shm.buf, slot_offset, len(data_bytes))
        self.shm.buf[slot_offset+4 : slot_offset+4+len(data_bytes)] = data_bytes
        
        # 原子更新写索引
        struct.pack_into('<Q', self.shm.buf, 0, w_idx + 1)
        return True

    def pop(self):
        """QMT内部策略调用：读取信号"""
        w_idx, r_idx = struct.unpack_from('<QQ', self.shm.buf, 0)
        
        if w_idx == r_idx:
            return None  # 队列为空
            
        slot_offset = 16 + (r_idx % MAX_SLOTS) * SLOT_SIZE
        data_len = struct.unpack_from('<I', self.shm.buf, slot_offset)[0]
        data_bytes = bytes(self.shm.buf[slot_offset+4 : slot_offset+4+data_len])
        
        # 原子更新读索引
        struct.pack_into('<Q', self.shm.buf, 8, r_idx + 1)
        
        return json.loads(data_bytes.decode('utf-8'))

    def close(self):
        self.shm.close()

    def unlink(self):
        self.shm.unlink()