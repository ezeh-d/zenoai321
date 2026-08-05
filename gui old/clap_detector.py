import sounddevice as sd
import numpy as np
import time

THRESHOLD = 0.25
WINDOW = 2.0
SAMPLE_RATE = 44100


def detect_double_clap():
    clap_count = 0
    first_clap_time = None

    while True:
        audio = sd.rec(
            int(0.2 * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1
        )
        sd.wait()

        volume = np.max(np.abs(audio))

        if volume > THRESHOLD:
            current_time = time.time()

            if clap_count == 0:
                clap_count = 1
                first_clap_time = current_time

            elif clap_count == 1 and (current_time - first_clap_time) <= WINDOW:
                return True

        if clap_count == 1 and (time.time() - first_clap_time) > WINDOW:
            clap_count = 0
            first_clap_time = None