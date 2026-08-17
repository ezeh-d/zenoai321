# ZENO Human Companion V2 — implementation and evidence report

Date: 2026-08-11  
Host: Windows 10 19045, Python 3.12.3, Intel i5-6300U (2C/4T), 7.87 GiB RAM, Intel HD 520, no CUDA

## Outcome

ZENO now has one browser-owned Windows microphone stream and one bounded backend `AudioManager` frame bus. Wake detection, VAD-bound utterance recording, speaker verification and diagnostics consume copies of that stream; no new backend owns or opens a microphone. Heavy experimental audio frameworks remain off.

The production speaker verifier is a real 3D-Speaker CAM++ English VoxCeleb ONNX model executed locally by `sherpa-onnx==1.13.5`, with one CPU inference thread and a verified model SHA-256. Enrollment uses five to eight varied recordings, validates audio and cross-sample consistency, stores DPAPI-protected embeddings, and discards raw audio. The decision bands are `OWNER_HIGH`, `OWNER_LIKELY`, `UNCERTAIN` and `UNKNOWN`. Voice identity is evidence, never sensitive-action authentication.

The dashboard and Mini Orb now use real `FINISHED`, `UNFINISHED` and `WAIT` turn decisions after stable STT. Provider text is displayed token-by-token and complete clauses enter an abortable sentence TTS queue before the full model answer finishes. Barge-in cancels the TTS fetch/playback and the managed generation. Cached wake acknowledgements never call ElevenLabs on the realtime route.

## Repository audit

The current default README, repository license and stated platform/runtime requirements were inspected on 2026-08-11. Model weights can carry terms different from repository code, so ZENO does not infer model redistribution rights from the code license.

| Repository | Code/license and platform finding | Decision | ZENO result |
|---|---|---|---|
| speechbrain/speechbrain | Apache-2.0; PyTorch toolkit; speaker recognition includes ECAPA-TDNN, ResNet and x-vectors | FALLBACK | Not installed. Proven alternative, but Torch cost is unsuitable for the permanent path on this host. |
| modelscope/3D-Speaker | Apache-2.0; upstream workflow is Linux-oriented; publishes CAM++, ECAPA and ERes2Net-family speaker models | PRIMARY | English VoxCeleb CAM++ ONNX is deployed through the native Windows sherpa runtime. |
| modelscope/ClearerVoice-Studio | Apache-2.0; PyTorch speech enhancement/separation/target extraction | EXPERIMENTAL | Not deployed. It may be activated adaptively only after owner/noise-corpus WER and latency tests. |
| TEN-framework/ten-vad | Apache-2.0 plus repository conditions; Windows native library/WASM available; documented Python matrix does not cover this Python 3.12/numpy 2.5 host | EXPERIMENTAL | Not installed; current single browser VAD remains production. |
| TEN-framework/ten-turn-detection | Apache-family repository terms; current detector uses a Qwen2.5-7B stack | REJECTED | Rejected from the realtime host; a bounded English/Pidgin heuristic runs only at candidate turn boundaries. |
| xiph/rnnoise | BSD-3-Clause; native C/RNN noise suppression | EXPERIMENTAL | No audited Windows binary is deployed. WebRTC suppression remains primary; existing spectral suppression is opt-in. |
| microsoft/Windows-classic-samples AcousticEchoCancellation | Microsoft sample repository; driver/APO-oriented AEC reference, not a drop-in Python user API | ARCHITECTURAL_REFERENCE | WebView2/WebRTC `echoCancellation` is requested and its applied track setting is reported. |
| ufal/SimulStreaming | MIT; incremental Whisper research implementation; useful high-end profiles expect substantially stronger GPU resources | REJECTED | Not installed on this CPU-only realtime host. |
| FunAudioLLM/SenseVoice (requested as QwenAudio/SenseVoice) | MIT code; model terms are separate; PyTorch/FunASR-oriented multilingual/audio-event stack | EXPERIMENTAL | Optional adapter reports not configured; it never supplies identity or permissions. |
| FunAudioLLM/CosyVoice (requested as QwenAudio/CosyVoice) | Apache-2.0 code; large PyTorch model/runtime stack | EXPERIMENTAL | Not loaded; ElevenLabs remains the configured identity voice. |
| hexgrad/kokoro | Apache-2.0; small model but still requires a local inference/phonemizer stack | FALLBACK | Lazy optional TTS route; no model is claimed ready. |
| OHF-Voice/piper1-gpl | GPL-3.0; Windows-capable local TTS successor | FALLBACK | Lazy emergency candidate; distribution/license review and a configured model are required. |
| pipecat-ai/pipecat | BSD-2-Clause; realtime pipeline/WebRTC framework | ARCHITECTURAL_REFERENCE | Not allowed to create a competing microphone or runtime. |
| TEN-framework/ten-framework | Apache-2.0 plus repository conditions; realtime multimodal orchestration framework | ARCHITECTURAL_REFERENCE | Not installed; ZENO retains its existing kernel/Event Bus/realtime owner. |
| facebookresearch/seamless_communication | MIT code with separately licensed models; large Linux/PyTorch-oriented multilingual stack | REJECTED | Not practical locally on this host; future remote/backend reference only. |
| clovaai/aasist | MIT; PyTorch anti-spoof research model with domain-dependent calibration | EXPERIMENTAL | Not deployed. `spoof_score` remains `null/NOT_AVAILABLE`; sensitive work never trusts voice alone. |
| k2-fsa/sherpa-onnx | Apache-2.0; explicitly supports Windows x64/arm64, Python and speaker verification | PRIMARY | `1.13.5` deployed with one-thread CPU speaker inference. |
| dscripka/openWakeWord | Apache-2.0 code; bundled pretrained model licensing is more restrictive; ONNX local keyword spotting | PRIMARY | `0.6.0` adapter is installed and consumes the shared bus. A custom ZENO model is still absent, so it is truthfully `MODEL_NOT_CONFIGURED`. |
| snakers4/silero-vad | MIT; small ONNX/Torch VAD with broad CPU support | FALLBACK | Not installed. It should replace the current VAD only after a real same-corpus comparison. |
| SYSTRAN/faster-whisper | MIT; CTranslate2 Whisper, CPU int8 supported | FALLBACK | `1.2.1` installed; a model loads only when explicitly configured, preventing surprise downloads/startup cost. |

## Architecture delivered

1. WebView2 owns the one `getUserMedia` stream and requests Windows-respecting WebRTC AEC, noise suppression and automatic gain control.
2. `vad.js` exposes reusable PCM frames from that exact stream.
3. An authenticated WebSocket copies 16 kHz mono PCM to one bounded `AudioManager` queue (capacity 32, drop-oldest under pressure, one reusable worker, isolated consumer failures). Each WebView identifies itself only after capability-token authentication, so diagnostics report the real current capture owner. A single capped-backoff reconnect timer replaces the former two-attempt limit.
4. openWakeWord receives shared frames only when a custom model is configured. It never opens a device.
5. VAD-approved WAV copies go to CAM++ speaker verification and WebM goes to STT in the existing priority worker pool.
6. The turn detector runs only on stable final text near an endpoint. It never runs a model per audio frame.
7. FAST/DEEP routing reuses ZENO's existing sub-millisecond cognition router. No second brain was added.
8. Model text streams through the existing SSE route. Complete clauses are synthesized and played in order while later text continues arriving.
9. Unknown voices use clean non-persistent history and private tool denials. Only `OWNER_HIGH` may receive private conversational context; consequential actions still require the existing stronger confirmation path.

## Primary implementation decisions

- **Primary speaker verification:** 3D-Speaker CAM++ English VoxCeleb via sherpa-onnx. It is the only candidate actually verified on Windows/Python 3.12 without Torch.
- **Primary noise suppression:** browser/WebRTC native suppression; the existing single-pass spectral suppressor remains opt-in for stationary noise. RNNoise is not claimed deployed.
- **Primary target-speaker extraction:** not deployed. ClearerVoice remains experimental until owner/overlap measurements justify its latency.
- **Primary VAD:** the existing adaptive browser energy VAD. It is the only active VAD.
- **Primary turn detector:** bounded English/Nigerian-English/Pidgin heuristic at stable STT boundaries. TEN's 7B detector is rejected on this hardware.
- **Primary STT:** Deepgram Nova-3 final-clip route with vocabulary keyterms. Explicit faster-whisper int8 local fallback is available but has no configured model. The current route emits only `STT_FINAL`; it does not fake partial events.
- **Primary realtime framework:** local WebView2 AudioManager/Event Bus. Existing LiveKit remains remote-mode infrastructure; Pipecat and TEN do not run.
- **Primary TTS:** ElevenLabs with ZENO's configured voice, cache and sentence-level queue.
- **Local TTS fallback:** Windows SAPI in non-dashboard failure paths; Kokoro/Piper stay lazy candidates. The dashboard does not switch voices mid-response.
- **Anti-spoof:** not deployed. AASIST remains experimental and cannot authorize sensitive actions.
- **AEC:** WebView2/WebRTC `echoCancellation`, validated from actual applied track settings. Microsoft's APO sample is a design reference only.
- **Multilingual backend:** Deepgram English/Nigerian context plus ZENO's existing Pidgin-aware cognition and a bounded session language observer. No dedicated Nigerian local model is claimed.

## Measurements

### Real local speaker control clips

The official English SpeechBrain control clips were used only to verify that the deployed embedding model distinguishes same and different speakers. They are not Divine and therefore are not an owner-accuracy test.

| Clip | Duration | Model inference | End-to-end embedding wall time |
|---|---:|---:|---:|
| speaker 1 / utterance 1 | 2.87 s | 85.56 ms | 1728.47 ms cold |
| speaker 1 / utterance 2 | 3.15 s | 80.18 ms | 89.09 ms warm |
| speaker 2 / utterance 1 | 2.01 s | 49.32 ms | 55.03 ms warm |

- Lazy model load: 1371.36 ms.
- Same-speaker cosine: 0.7685.
- Different-speaker cosine: 0.3508.
- These three control clips prove functional separation, not production accuracy or a tuned ROC curve.

### Live idle snapshot

- Exact live ZENO process tree: 12 processes, 314.3 MiB working set, 188 OS threads.
- Five-second total CPU snapshot: 4.22% of machine capacity.
- Three-second matching WebView2 GPU-engine sample: 0.57% summed average.
- The Human Companion status path is lazy: first import/status was 1040 ms and added about 21 MiB in the diagnostic process; repeated status calls were 9.9–12.7 ms.
- FAST/DEEP router: 1000 Pidgin/project routes averaged 0.0244 ms; worst observed route was 16.7455 ms.
- All seven configured wake acknowledgement clips exist in the real ElevenLabs cache.

### Live frame bus

The first live run exposed a real lifecycle defect: after the dashboard was minimized, its pywebview minimize event did not fire. The dashboard had taken microphone ownership, the Mini Orb therefore remained stopped, and the shared-frame count stalled at 1,444. The existing five-second native overlay watchdog now checks the dashboard HWND directly (`IsWindowVisible` + `IsIconic`) and repairs a missed open/hidden handoff without activating either window. Both WebSocket clients now keep one capped-backoff reconnect timer instead of giving up permanently after two failures.

After the first patched desktop restart, a 151-second live soak advanced from 1,801 to 3,567 frames (about 11.7 frames/s). Every one of the 11 samples reported `webview2-mini-orb`, `MICROPHONE_READY`, live audio, queue depth zero, zero dropped frames and zero consumer errors. The host and Mini Orb processes both remained Windows-responsive.

The complete 54-file test load then exposed a second edge of the same lifecycle bug: an Event Bus storm could fill the Mini Orb subscriber queue and drop the one dashboard-hidden event. Native state was already correct, but the renderer never received it, so frames later stopped at 5,866. The final repair makes the dashboard release capture directly on `document.visibilitychange` and returns native dashboard ownership on the Mini Orb's existing one-second host heartbeat. This adds no timer and makes a dropped lifecycle event recoverable. After the final restart, six samples advanced from 69 to 255 frames with the same zero-depth/zero-drop/zero-error live Mini Orb owner. The 151-second soak proves stable idle capture; the post-load discovery and stronger repair remain honestly distinguished from the still-required audible owner wake/barge-in trials.

### Latency measurements

The live `/api/diagnostics/latency` report currently contains zero completed real voice turns, zero wake acknowledgements and zero barge-ins. Median, P90, P95 and worst are therefore `null`, not zero. The 150–400 ms wake target and <=1.5 s normal-response median are **not yet proven**.

## Test status

- Dedicated Human Companion V2: 9/9 passed.
- FAST/DEEP cognition and endpointing: 26/26 passed.
- Conversation state/cancellation: 18/18 passed.
- Microphone diagnosis/repair: 7/7 passed.
- Speech repair: 3/3 passed.
- Full standalone matrix initial run: 50/53 files passed in 240.1 s; three failures were investigated and repaired.
- A concurrent Phase 1 package rename briefly produced one import-shadowing failure; after the rename, Phase 1 passed 38/38 and connector/specialist coverage passed 21/21.
- Complete combined standalone matrix immediately before the final lifecycle guard: 54/54 files passed in 306.6 s.
- Final Human/voice/lifecycle targeted run before the heartbeat guard: 25/25 passed (voice handoff 4, Human Companion 9, in-app microphone 4, speech repair 3, Living Recognition 5); every changed surface after the final guard passed 18/18 across voice handoff, in-app microphone and Human Companion.
- Other targeted reruns after repair: confidence 5/5 and Phase 5 security/power 21/21.
- Python compileall and JavaScript module parsing passed.

## Honest incomplete acceptance work

The following require owner participation or hardware/data that does not exist in the repository:

1. Divine has not enrolled a model-backed voice profile. Owner normal/quiet/tired/distance accuracy, unknown/similar-gender accuracy and ROC threshold tuning are unmeasured.
2. No consented owner + TV/other-speaker/noise corpus exists. ClearerVoice WER, target-owner priority and fan/music/TV/keyboard/street comparisons are unmeasured.
3. AASIST is disabled. Live/replay/phone/speaker/cloned-voice discrimination is unmeasured.
4. No custom ZENO openWakeWord model exists. The fast local wake trigger is not active even though the shared-frame adapter and seven cached replies are ready.
5. No 50-turn interactive owner session has been recorded. Wake, barge-in and response latency percentiles remain absent.
6. Self-hearing at speaker volumes 25/50/75/100 needs an audible WebView2 test with the owner present.
7. TEN VAD, Silero, Sherpa VAD, ClearerVoice, SenseVoice, CosyVoice and Kokoro were not installed merely to manufacture a comparison. The included manifest benchmark runner accepts real consented WAV clips and records speaker accuracy, latency, memory and optional billable STT WER without retaining audio.

## 2026-08-11 response-budget addendum

The <=1.5-second work is now implemented as a truthful audible-response
budget, not as a false promise that arbitrary cloud reasoning finishes inside
that time. Exact consequence-free social replies use a local allowlist and
pre-generated ZENO ElevenLabs clips. Other spoken turns schedule a cache-only
progress line at 650 ms; the real answer interrupts it on its first audio frame
and barge-in cancels both.

The accidental default payload of 94 tool schemas / 44,588 JSON characters was
reduced to 12 entry schemas, and pure FAST chat sends none. Its system prompt is
about 1.4k characters instead of the 18k action manual. On the restarted live
server, `how you dey` returned text in 63.34 ms and cached audio bytes in 10.95
ms (74.29 ms combined server-side). The cache-only thinking endpoint measured
10.79 ms median over five requests. The owner-spoken browser `first_audio`
sample is still absent, so no end-to-end voice median is claimed. The current
Gemini connection remains the bottleneck: one real non-local turn measured
15.914 seconds to first text, while OpenAI returned `insufficient_quota`.

Run the real corpus harness with:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_human_companion.py C:\path\manifest.jsonl --output C:\path\results.json
```

Add `--allow-cloud-stt` only when a billable WER run is intended.
