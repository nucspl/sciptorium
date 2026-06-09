import signal
import subprocess
from collections import Counter, defaultdict as DefaultDict
from collections.abc import Iterator
from contextlib import suppress as Suppress
from datetime import datetime as DateTime, timedelta as TimeDelta
from functools import partial as Partial
from itertools import chain as Chain, takewhile as TakeWhile
from subprocess import Popen
from threading import Event, Thread
from typing import Any

from fire import Fire
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner


# -- prep


console = Console(color_system=None, highlight=False)
Live = Partial(Live, refresh_per_second=60, transient=True, console=console)


# -- stop


def stage_events() -> tuple[Event, Event]:
    _signal_event, _stop_event = Event(), Event()

    def notify_stop() -> None:
        _signal_event.wait()
        with Live(Spinner('dots', 'Stopping')):
            _stop_event.wait()

    def cascade_stop() -> None:
        _stop_event.wait()
        handle_signal()

    def handle_signal(*_: Any) -> None:
        _signal_event.set()

    for s in signal.valid_signals():
        with Suppress(OSError, ValueError):
            signal.signal(s, handle_signal)

    Thread(target=notify_stop).start()
    Thread(target=cascade_stop).start()
    return _signal_event, _stop_event


signal_event, stop_event = stage_events()


# -- main


def spawn(link: str) -> Iterator[str]:
    with Popen(
      ('gallery-dl', link),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True) as popen:
        if not popen.stdout or not popen.stderr:
            popen.terminate()
            return

        for _ in TakeWhile(
          lambda _: not signal_event.is_set(),
          Chain(popen.stdout, popen.stderr)):
            yield _.strip()


def cycle(*links: str, time: DateTime) -> None:
    items: dict[str, list[str]] = DefaultDict(list)
    with Live(spinner := Spinner('dots')):
        for a, b in TakeWhile(
          lambda _: not signal_event.is_set(),
          enumerate(links)):
            spinner.update(text=f'[{a + 1}/{len(links)}] {b}')
            for c in spawn(b):
                if (d := c[0]) in ('.', '#', '['):
                    items[d].append(c)
                if d != '#':
                    console.print(c)

    downloads, skips, errors = (
      len(items['.']), len(items['#']), len(items['[']))

    if not downloads and not skips and errors:
        console.print('! All provided links failed.')
        stop_event.set()
        return

    console.print(
      f'[{time.astimezone():%Y-%m-%dT%H:%M:%SZ}] {downloads + skips} items '
      f'processed: {downloads} downloaded; {skips} skipped.',
      sep='\n')


def main(*links: str, interval: int = 1800) -> None:
    """
    Routinely runs gallery-dl while omitting unnecessary console printing.
    Args:
        interval: How many seconds to wait with each gallery-dl run.
    """
    if not links:
        console.print('! No links were provided.')
        stop_event.set()
        return

    counter = Counter(links)
    if any(_ > 1 for _ in counter.values()):
        links = tuple(counter.keys())
        console.print('* Duplicates found, sanitised links:')
        console.print(*links, sep='\n', end='\n' * 2)

    while not signal_event.is_set():
        cycle(*links, time=(time := DateTime.now()))
        time += TimeDelta(seconds=interval)
        with Live(Spinner('dots', f'Waiting until {time:%H:%M:%S}')):
            while not signal_event.is_set() and time > DateTime.now():
                signal_event.wait(1)

    stop_event.set()


if __name__ == '__main__':
    Fire(main)
