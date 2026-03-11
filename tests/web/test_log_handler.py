import logging
from zalosniper.web.log_handler import RingBufferHandler

def test_captures_log_records():
    handler = RingBufferHandler(maxlen=10)
    logger = logging.getLogger("test_capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.info("hello world")
    logger.error("something went wrong")

    lines = handler.get_lines()
    assert len(lines) == 2
    assert any("hello world" in l["message"] for l in lines)
    assert any(l["level"] == "ERROR" for l in lines)

def test_ring_buffer_max_size():
    handler = RingBufferHandler(maxlen=3)
    logger = logging.getLogger("test_ring")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    for i in range(5):
        logger.info(f"msg {i}")

    lines = handler.get_lines()
    assert len(lines) == 3
    assert lines[-1]["message"].endswith("msg 4")
