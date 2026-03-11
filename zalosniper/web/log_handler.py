import logging
from collections import deque
from datetime import datetime
from typing import List


class RingBufferHandler(logging.Handler):
    """In-memory log handler that keeps the last `maxlen` records."""

    def __init__(self, maxlen: int = 200) -> None:
        super().__init__()
        self._buffer: deque = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append({
            "timestamp": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "message": self.format(record),
        })

    def get_lines(self, level: str = None) -> List[dict]:
        lines = list(self._buffer)
        if level:
            lines = [l for l in lines if l["level"] == level.upper()]
        return lines


# Global singleton — installed in main.py
ring_handler = RingBufferHandler(maxlen=200)
