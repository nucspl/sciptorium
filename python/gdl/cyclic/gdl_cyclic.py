import signal
import subprocess
from collections import Counter
from contextlib import suppress as Suppress
from datetime import (
    datetime as DateTime,
    timedelta as TimeDelta,
    timezone as TimeZone,
)
from functools import partial as Partial
from subprocess import Popen
from threading import Event, Thread
from typing import Any, Iterator

from fire import Fire
from rich import live
from rich.console import Console
from rich.spinner import SPINNERS, Spinner

# -- preparation


SPINNERS.update({
    'blink': {
        'interval': 100,
        'frames': '   ·*·',
    },
    'snake_6_4': {
        'interval': 100,
        'frames': '⠧⠏⠛⠹⠼⠶',
    },
})

console = Console(
    color_system=None,
    highlight=False,
)
Live = Partial(
    live.Live,
    refresh_per_second=60,
    transient=True,
    console=console,
)


# -- stop


def watch_signal() -> tuple[Event, Event]:
    """
    A factory which creates a threading.Event handling stop signals.
    """
    signal_event, stop_event = Event(), Event()

    def notify_signal() -> None:
        signal_event.wait()
        with Live(Spinner('grenade', 'Stopping')):
            stop_event.wait()

    def handle_signal(*_: Any) -> None:
        return signal_event.set()

    for s in signal.valid_signals():
        with Suppress(OSError, ValueError):
            signal.signal(s, handle_signal)

    Thread(target=notify_signal, daemon=True).start()
    return signal_event, stop_event


signal_event, stop_event = watch_signal()


# -- main


def spawn(link: str) -> Iterator[str]:
    with Popen(
        ('gallery-dl', link),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as popen:
        if popen.stdout:
            for _ in popen.stdout:
                if signal_event.is_set():
                    return popen.terminate()
                yield _.strip()


def cycle(*links: str) -> DateTime:
    processed: list[str] = []

    with Live(spinner := Spinner('snake_6_4')) as live:
        for a, b in enumerate(links):
            if signal_event.is_set():
                break
            spinner.update(text=f'[{a + 1}/{len(links)}]: {b}')
            for _ in spawn(b):
                if not _.startswith('#'):
                    live.console.print(_)
                processed.append(_)

    downloaded, skipped, time = (
        sum(1 for _ in processed if not _.startswith('#')),
        sum(1 for _ in processed if _.startswith('#')),
        DateTime.now(TimeZone.utc).astimezone(),
    )

    console.print(
        f'[{time:%Y-%m-%dT%H:%M:%SZ}] '
        f'{len(processed)} items processed: '
        f'{downloaded} downloaded; '
        f'{skipped} skipped.',
        sep='\n',
    )

    return time


def main(*links: str, interval: int = 3600) -> None:
    """
    Routinely runs gallery-dl while omitting unnecessary console printing.
    Args:
        interval: How many seconds to wait for after each gallery-dl run.
    """
    if any(_ > 1 for _ in Counter(links).values()):
        links = tuple(dict.fromkeys(links))
        console.print('* Duplicates found and sanitised.')
    console.print(*links, sep='\n', end='\n' * 2)

    while not signal_event.is_set():
        time = cycle(*links) + TimeDelta(seconds=interval)
        with Live(spinner := Spinner('blink')):
            spinner.update(text=f'Waiting until {time:%Y-%m-%dT%H:%M:%SZ}.')
            signal_event.wait(interval)

    return stop_event.set()


if __name__ == '__main__':
    Fire(main)
