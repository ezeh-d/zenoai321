# Resource monitoring candidates

- `psutil`: selected local provider for portable process/system CPU, RAM, disk,
  battery, network counters and thread counts. It is already compatible with the
  project and is sampled only on demand.
- Windows APIs: retain for window/process ownership where ZENO already uses them;
  not needed for the general pressure loop.
- NVIDIA/AMD/Intel vendor telemetry: potentially supplies GPU/VRAM data, but no
  universal maintained Windows API is guaranteed on this device. Keep optional
  and do not load vendor SDKs on startup.

The Resource Governor controls existing admission budgets and idle cleanup.
ECO/BALANCED/PERFORMANCE/MAX are resource policies, not promises of speed. Voice,
STOP, VAD, turn detection and interactive routing remain reserved at every
profile.
