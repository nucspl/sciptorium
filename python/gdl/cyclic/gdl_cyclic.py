import signal
import subprocess
import sys
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


def cycle(links: list[str], time: DateTime, keep_links: bool) -> None:
    items: dict[str, list[str]] = DefaultDict(list)
    with Live(spinner := Spinner('dots')):
        for a, b in TakeWhile(
          lambda _: not signal_event.is_set(),
          enumerate(links)):
            spinner.update(text=f'[{a + 1}/{len(links)}] {b}')
            for c in spawn(b):
                items[(d := c[0])].append(c)
                if d == '[' and not keep_links:
                    links.remove(b)
                    break
                if d != '#':
                    console.print(c)

    downloads, skips, errors = (
      len(items['.']), len(items['#']), len(items['[']))

    if not (downloads or skips) and errors:
        console.print('! All provided links failed.')
        if not links:
            stop_event.set()
            return

    console.print(
      f'[{time.astimezone():%Y-%m-%dT%H:%M:%SZ}] {downloads + skips} items '
      f'processed: {downloads} downloaded; {skips} skipped.',
      sep='\n')


def main(
  *links: str,
  interval: int = 1800,
  keep_links: bool = False) -> None:
    """
    Routinely runs gallery-dl while omitting unnecessary console printing.
    Args:
        interval: Wait this many seconds with each gallery-dl run.
        keep_links: Do not remove links when gallery-dl reports errors.
    """
    _links = list(links)
    if not _links:
        console.print('! No links were provided.')
        stop_event.set()
        return

    counter = Counter(_links)
    if any(_ > 1 for _ in counter.values()):
        _links = list(counter.keys())
        console.print('* Duplicates found, sanitised links:')
        console.print(*_links, sep='\n', end='\n' * 2)

    while _links and not signal_event.is_set():
        cycle(_links, time := DateTime.now(), keep_links)
        time += TimeDelta(seconds=interval)
        with Live(Spinner('dots', f'Waiting until {time:%H:%M:%S}')):
            while all((
                  not signal_event.is_set(),
                  time > DateTime.now(),
                  _links)):
                signal_event.wait(1)

    stop_event.set()


if __name__ == '__main__':
    if not len(sys.argv[1:]):
        sys.argv.append('--help')

    try:
        Fire(main)
    except SystemExit:
        stop_event.set()
