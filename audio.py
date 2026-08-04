#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio.py — избор на изходно устройство ПО ИМЕ, декодиране на mp3 и една
единствена опашка за възпроизвеждане (без застъпваща се реч).

Декодирането минава първо през `miniaudio` (малко pip колело, без външни
зависимости), а ако него го няма — през `pydub`/ffmpeg. Така run.bat тръгва
на чиста машина, без ръчна инсталация на ffmpeg.

Възпроизвеждането е в отделна нишка: пише на блокове, за да може SKIP да
подейства веднага, вместо да чака края на записа.

CLI:
    python audio.py --list-devices
    python audio.py --test                      # тон 440 Hz на устройството по подразбиране
    python audio.py --test --device "Voicemeeter"
"""

from __future__ import annotations

import logging
import math
import queue
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Union

log = logging.getLogger(__name__)

try:  # audioop е в стандартната библиотека до 3.12
    import warnings

    with warnings.catch_warnings():
        # Знаем, че отпада в 3.13 — по-долу има резервен вариант без него.
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop  # type: ignore
except Exception:  # pragma: no cover
    audioop = None  # type: ignore

#: Размер на блока при писане към звуковата карта (в кадри).
#: 1024 кадъра при 24 kHz ≈ 43 ms — достатъчно бързо за SKIP.
BLOCK_FRAMES = 1024


class AudioError(RuntimeError):
    """Проблем със звука, с готово съобщение на български."""


# ---------------------------------------------------------------------------
# Устройства
# ---------------------------------------------------------------------------


@dataclass
class OutputDevice:
    index: int
    name: str
    channels: int
    samplerate: float
    hostapi: str = ""
    is_default: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} ({self.hostapi})" if self.hostapi else self.name


def _sd():
    """Внася sounddevice чак когато потрябва — за да не пада всичко без PortAudio."""
    try:
        import sounddevice as sd  # noqa: WPS433
    except OSError as exc:
        raise AudioError(
            "Няма достъп до звуковата система (PortAudio не е намерен). "
            "Преинсталирай пакета sounddevice."
        ) from exc
    except ImportError as exc:
        raise AudioError(
            "Липсва пакетът sounddevice. Пусни: pip install -r requirements.txt"
        ) from exc
    return sd


def list_output_devices() -> List[OutputDevice]:
    """Всички изходни устройства. Празен списък, ако звукът е недостъпен."""
    try:
        sd = _sd()
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        try:
            default_out = sd.default.device[1]
        except Exception:
            default_out = None
    except AudioError as exc:
        log.warning("Няма изходни устройства: %s", exc)
        return []
    except Exception as exc:
        log.warning("Изброяването на устройства се провали: %s", exc)
        return []

    out: List[OutputDevice] = []
    for idx, dev in enumerate(devices):
        if dev.get("max_output_channels", 0) < 1:
            continue
        api_idx = dev.get("hostapi", -1)
        api_name = ""
        if 0 <= api_idx < len(hostapis):
            api_name = hostapis[api_idx].get("name", "")
        out.append(
            OutputDevice(
                index=idx,
                name=dev.get("name", f"устройство {idx}"),
                channels=int(dev.get("max_output_channels", 2)),
                samplerate=float(dev.get("default_samplerate", 48000.0)),
                hostapi=api_name,
                is_default=(idx == default_out),
            )
        )
    return out


def resolve_device(spec: Union[str, int, None]) -> Optional[int]:
    """Име (или част от име) -> индекс. None = устройството по подразбиране.

    По име, защото индексите на Windows се разместват при всяко закачане на
    слушалки, а "Voicemeeter Input" си остава "Voicemeeter Input".
    """
    if spec is None or spec == "" or spec == "default":
        return None
    if isinstance(spec, int):
        return spec
    if isinstance(spec, str) and spec.isdigit():
        return int(spec)

    devices = list_output_devices()
    if not devices:
        return None
    needle = str(spec).strip().lower()
    for dev in devices:  # точно съвпадение
        if dev.name.lower() == needle:
            return dev.index
    for dev in devices:  # частично съвпадение
        if needle in dev.name.lower():
            return dev.index
    log.warning("Устройство %r не е намерено — ползвам това по подразбиране", spec)
    return None


def device_name(index: Optional[int]) -> str:
    if index is None:
        return "по подразбиране"
    for dev in list_output_devices():
        if dev.index == index:
            return dev.name
    return f"устройство {index}"


# ---------------------------------------------------------------------------
# Декодиране
# ---------------------------------------------------------------------------


@dataclass
class Clip:
    """Декодиран звук, готов за изсвирване."""

    pcm: bytes  # int16, little-endian, преплетени канали
    samplerate: int
    channels: int
    #: Изходните mp3 байтове — пазим ги, за да можем да предекодираме с друга
    #: честота, ако устройството не приема 24 kHz.
    source: Optional[bytes] = None
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        frames = len(self.pcm) / 2 / max(self.channels, 1)
        return frames / max(self.samplerate, 1)


def decode_audio(
    data: bytes, samplerate: int = 24000, channels: int = 1
) -> Clip:
    """mp3/wav байтове -> Clip с int16 PCM. Първо miniaudio, после pydub."""
    if not data:
        raise AudioError("Празни аудио данни за декодиране.")

    try:
        import miniaudio  # noqa: WPS433

        decoded = miniaudio.decode(
            data,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=channels,
            sample_rate=samplerate,
        )
        return Clip(
            pcm=decoded.samples.tobytes(),
            samplerate=decoded.sample_rate,
            channels=decoded.nchannels,
            source=data,
        )
    except ImportError:
        log.debug("miniaudio липсва — минавам на pydub/ffmpeg")
    except Exception as exc:
        log.warning("miniaudio не успя да декодира (%s) — минавам на pydub", exc)

    try:
        import io

        from pydub import AudioSegment  # noqa: WPS433

        seg = AudioSegment.from_file(io.BytesIO(data))
        seg = seg.set_frame_rate(samplerate).set_channels(channels).set_sample_width(2)
        return Clip(
            pcm=seg.raw_data,
            samplerate=seg.frame_rate,
            channels=seg.channels,
            source=data,
        )
    except ImportError as exc:
        raise AudioError(
            "Няма как да декодирам звука: липсват и miniaudio, и pydub. "
            "Пусни: pip install -r requirements.txt"
        ) from exc
    except Exception as exc:
        raise AudioError(
            "Звукът не може да бъде декодиран. Ако ползваш pydub, провери "
            "дали ffmpeg е инсталиран и е в PATH."
        ) from exc


def make_tone(
    freq: float = 440.0, seconds: float = 0.6, samplerate: int = 24000
) -> Clip:
    """Кратък тон — за проверка на устройството без синтез."""
    n = int(samplerate * seconds)
    fade = max(int(samplerate * 0.02), 1)
    out = bytearray()
    for i in range(n):
        amp = 0.25
        if i < fade:
            amp *= i / fade
        elif i > n - fade:
            amp *= (n - i) / fade
        value = int(32767 * amp * math.sin(2 * math.pi * freq * i / samplerate))
        out += struct.pack("<h", value)
    return Clip(pcm=bytes(out), samplerate=samplerate, channels=1)


def _scale_volume(pcm: bytes, factor: float) -> bytes:
    """Промяна на силата върху int16 буфер."""
    if factor >= 0.999 and factor <= 1.001:
        return pcm
    factor = max(0.0, min(factor, 4.0))
    if audioop is not None:
        return audioop.mul(pcm, 2, factor)
    # Резервен вариант без audioop (Python 3.13+)
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    for i, value in enumerate(samples):
        scaled = int(value * factor)
        samples[i] = 32767 if scaled > 32767 else (-32768 if scaled < -32768 else scaled)
    return samples.tobytes()


# ---------------------------------------------------------------------------
# Плейър
# ---------------------------------------------------------------------------


class AudioPlayer:
    """Една опашка, една нишка, никаква застъпваща се реч."""

    def __init__(
        self,
        device: Union[str, int, None] = None,
        volume: float = 1.0,
        queue_max: int = 15,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self._queue: "queue.Queue[Optional[Clip]]" = queue.Queue()
        self._queue_max = max(1, int(queue_max))
        self._device_spec = device
        self._device_index = resolve_device(device)
        self._volume = float(volume)
        self._muted = False
        self._skip = threading.Event()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._current: Optional[Clip] = None
        self._on_event = on_event
        self.dropped = 0
        self.played = 0
        self.last_error: Optional[str] = None

    # -- състояние ---------------------------------------------------------

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current(self) -> Optional[Clip]:
        return self._current

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def device_index(self) -> Optional[int]:
        return self._device_index

    def _emit(self, name: str, payload: Optional[dict] = None) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(name, payload or {})
        except Exception:  # обратната връзка никога не бива да спира звука
            log.exception("Грешка в обработчик на аудио събитие %s", name)

    # -- управление --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._worker, name="audio-player", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._running.clear()
        self._skip.set()
        self._queue.put(None)  # събуждаме нишката
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def set_device(self, spec: Union[str, int, None]) -> Optional[int]:
        with self._lock:
            self._device_spec = spec
            self._device_index = resolve_device(spec)
        log.info("Изход: %s", device_name(self._device_index))
        return self._device_index

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(float(volume), 2.0))

    def set_mute(self, muted: bool) -> None:
        self._muted = bool(muted)
        if muted:
            self.clear()
            self.skip()

    def toggle_mute(self) -> bool:
        self.set_mute(not self._muted)
        return self._muted

    def skip(self) -> None:
        """Прекъсва текущото възпроизвеждане."""
        self._skip.set()

    def clear(self) -> int:
        """Изпразва опашката. Връща броя изхвърлени."""
        removed = 0
        while True:
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                if item is not None:
                    removed += 1
            except queue.Empty:
                break
        if removed:
            self._emit("queue_cleared", {"removed": removed})
        return removed

    def enqueue(self, clip: Clip) -> bool:
        """Добавя в опашката. При пълна опашка изхвърля НАЙ-СТАРОТО."""
        if self._muted:
            self.dropped += 1
            return False
        while self._queue.qsize() >= self._queue_max:
            try:
                old = self._queue.get_nowait()
                self._queue.task_done()
                if old is not None:
                    self.dropped += 1
                    self._emit("dropped", {"reason": "пълна опашка", "meta": old.meta})
            except queue.Empty:
                break
        self._queue.put(clip)
        return True

    # -- нишка -------------------------------------------------------------

    def _worker(self) -> None:
        while self._running.is_set():
            try:
                clip = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if clip is None or not self._running.is_set():
                    continue
                if self._muted:
                    self.dropped += 1
                    continue
                self._skip.clear()
                self._current = clip
                self._emit("start", {"meta": clip.meta, "duration": clip.duration})
                self._play(clip)
                self.played += 1
                self._emit("finish", {"meta": clip.meta})
            except Exception as exc:  # едно лошо съобщение не спира цикъла
                self.last_error = str(exc)
                log.exception("Възпроизвеждането се провали")
                self._emit("error", {"error": str(exc), "meta": getattr(clip, "meta", {})})
            finally:
                self._current = None
                self._queue.task_done()

    def _open_stream(self, sd, clip: Clip, device: Optional[int]):
        return sd.RawOutputStream(
            samplerate=clip.samplerate,
            channels=clip.channels,
            dtype="int16",
            device=device,
            blocksize=BLOCK_FRAMES,
        )

    def _play(self, clip: Clip) -> None:
        sd = _sd()
        with self._lock:
            device = self._device_index

        try:
            stream = self._open_stream(sd, clip, device)
        except Exception as exc:
            # Устройството може да не приема 24 kHz — пробваме с неговата
            # честота, като предекодираме от изходния mp3.
            log.warning("Потокът не се отвори при %d Hz (%s)", clip.samplerate, exc)
            clip = self._redecode_for_device(clip, device)
            try:
                stream = self._open_stream(sd, clip, device)
            except Exception as exc2:
                raise AudioError(
                    f"Устройството '{device_name(device)}' не може да бъде отворено: {exc2}"
                ) from exc2

        frame_bytes = 2 * clip.channels
        block = BLOCK_FRAMES * frame_bytes
        with stream:
            for offset in range(0, len(clip.pcm), block):
                if self._skip.is_set() or self._muted or not self._running.is_set():
                    break
                chunk = clip.pcm[offset : offset + block]
                stream.write(_scale_volume(chunk, self._volume))

    def _redecode_for_device(self, clip: Clip, device: Optional[int]) -> Clip:
        if not clip.source:
            return clip
        target_rate = 48000
        target_channels = clip.channels
        for dev in list_output_devices():
            if device is None or dev.index == device:
                target_rate = int(dev.samplerate)
                target_channels = min(clip.channels, dev.channels) or 1
                break
        new_clip = decode_audio(
            clip.source, samplerate=target_rate, channels=target_channels
        )
        new_clip.meta = clip.meta
        return new_clip


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_devices() -> None:
    devices = list_output_devices()
    if not devices:
        print("Не са намерени изходни устройства.")
        return
    print(f"{'№':>3}  {'по подр.':<9} {'кан.':>4} {'Hz':>7}  име")
    print("-" * 72)
    for dev in devices:
        mark = "  <--" if dev.is_default else ""
        print(
            f"{dev.index:>3}  {'да' if dev.is_default else '':<9} "
            f"{dev.channels:>4} {int(dev.samplerate):>7}  {dev.label}{mark}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if "--list-devices" in argv or "-l" in argv or not argv:
        _print_devices()
        return 0

    device: Union[str, int, None] = None
    if "--device" in argv:
        device = argv[argv.index("--device") + 1]

    if "--test" in argv or "-t" in argv:
        player = AudioPlayer(device=device, on_event=lambda n, p: print(f"[{n}] {p}"))
        player.start()
        print(f"Изсвирвам тон на: {device_name(player.device_index)}")
        player.enqueue(make_tone())
        time.sleep(1.5)
        player.stop()
        if player.last_error:
            print(f"Грешка: {player.last_error}")
            return 1
        return 0

    _print_devices()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
