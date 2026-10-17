"""Startpunkt: python -m cat_satellite --config /etc/cat-satellite/config.yaml"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from cat_satellite.config import ConfigError, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Cat-Satellit (Wake-Word, Mikrofon, Lautsprecher)")
    parser.add_argument("--config", default="config.yaml", help="Pfad zur config.yaml")
    parser.add_argument(
        "--list-devices", action="store_true", help="Audio-Geräte anzeigen und beenden"
    )
    parser.add_argument(
        "--test-speaker", action="store_true", help="Signalton abspielen und beenden"
    )
    parser.add_argument(
        "--test-mic", action="store_true", help="3 s aufnehmen, Pegel anzeigen, beenden"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.list_devices:
        from cat_satellite.audio import list_devices

        print(list_devices())
        return
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        print(f"Konfiguration: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    from cat_satellite.audio import SoundDeviceInput, SoundDeviceOutput

    speaker = SoundDeviceOutput(config.output_device, config.beep)
    mic = SoundDeviceInput(config.input_device)
    if args.test_speaker:
        asyncio.run(speaker.beep())
        print("Signalton gespielt.")
        return
    if args.test_mic:
        asyncio.run(_test_mic(mic))
        return

    from cat_satellite.client import Satellite
    from cat_satellite.wakeword import OpenWakeWordDetector

    detector = OpenWakeWordDetector(config.wakeword_model, config.wakeword_threshold)
    satellite = Satellite(config, mic, speaker, detector)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(satellite.run())
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, task.cancel)
            except NotImplementedError:  # Windows
                pass
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


async def _test_mic(mic: object) -> None:
    import numpy as np

    count = 0
    async for frame in mic.frames():  # type: ignore[attr-defined]
        level = float(np.abs(np.frombuffer(frame, dtype="<i2")).mean())
        print(f"Pegel {level:7.0f} " + "#" * min(60, int(level / 150)))
        count += 1
        if count >= 38:  # ca. 3 s
            return


if __name__ == "__main__":
    main()
