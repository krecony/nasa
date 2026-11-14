"""Reading frames from a video with OpenCV."""

import cv2


def video_info(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {path}")
    info = {
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return info


def read_frames(path):
    """Yield (index, frame) for every frame. Frames are RGB uint8 arrays.

    Note: OpenCV gives BGR, we flip it to RGB here so the rest of the code
    can think in normal RGB.
    """
    cap = cv2.VideoCapture(str(path))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        yield i, frame[:, :, ::-1]
        i += 1
    cap.release()


def first_frame(path):
    for _, frame in read_frames(path):
        return frame
    raise ValueError(f"No frames in {path}")
