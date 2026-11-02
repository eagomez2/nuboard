# `timer`

```python
run.timer(name, step=None, *, accumulate=None, all_ranks=None, sync=None) -> Timer
```

Times a part of the training code, such as an epoch, a validation pass or a
callback, without decorators and without changing the timed code. The timer
works as a context manager or as a start/stop handle:

```python
with run.timer("train/epoch", step=epoch):     # a block
    train_one_epoch()

run.timer("val/epoch").start()                 # in one method...
run.timer("val/epoch").stop(step=epoch)        # ...and stopped in another

t = run.timer("ckpt/save").start()             # a handle, with the seconds back
save_checkpoint()
seconds = t.stop()
```

**The name is the handle**: `run.timer(name)` returns the same timer every time,
so a timer started in `on_validation_start` can be stopped in
`on_validation_end` without keeping it anywhere.

**Parameters**

- **name** (*str*): the timer's name, such as `"train/epoch"` or
  `"callbacks/Checkpoint.on_epoch_end"`. A `/` groups timers, as in scalar names.
- **step** (*int*, optional): the step of the next `stop` (or `flush`). Defaults
  to the step of the latest `add_scalar` call, as for system metrics; timers
  never move the step counter.
- **accumulate** (*bool*): sum the spans and log their total once per `flush()`,
  for a timer around every batch. Without it each `stop()` logs one point.
- **all_ranks** (*bool*): log from every rank, not only rank 0. Defaults to
  `nb.init(timing_all_ranks=...)`. See
  [Distributed training](../guide/distributed.md#timers).
- **sync** (*bool*): call `torch.cuda.synchronize()` at start and stop, so the
  time covers the GPU work and not only its launch. Only done when PyTorch is
  already imported; NuBoard never imports it.

`accumulate`, `all_ranks` and `sync` are fixed by the first call for a name;
a later call with a different value warns and keeps the first.

**Returns** a `Timer` with:

- `start()`: starts it and returns the timer.
- `stop(step=None)`: stops it, logs the span (or adds it to the total with
  `accumulate`) and returns its duration in seconds.
- `flush(step=None)`: with `accumulate`, logs the summed spans as one point and
  resets; returns the total.
- `elapsed`, `running`: the seconds since `start`, and whether it is running.
- `with timer: ...`: start and stop; it stops even when the block raises.

`nb.Timer.disabled(name)` returns a timer that measures but logs nothing, for
code that hands out timers before a run exists or on a rank that does not log.

**Mistakes never stop training.** Starting a running timer restarts it, and
stopping a stopped one returns 0.0, each with a one-time warning. A timer still
running at `finish()` is dropped with a warning (a half-finished epoch is not a
real duration); accumulated spans not yet flushed are logged. A timer that logs
every stop many times per second gets a one-time warning suggesting
`accumulate=True`.

**Raises** `ValueError` when `name` is empty or contains a control character.

**Stored as** a scalar named `timing/<name>` (`timing/<job>/<name>` in a
[helper job](../guide/jobs.md)): the value is the duration in seconds and the
point's time is when the span started. An accumulating timer also writes the
number of spans it summed under a hidden key. See
[Timing keys](../reference/format.md#timing-keys). A stop costs about a
microsecond and never blocks. To keep the word `timing` for your own scalars,
pick another prefix with `nb.init(timing_prefix=...)`; a scalar logged with
`add_scalar` under the run's timing or system prefix gets a one-time warning.

**In the viewer** timers are drawn in a **timing** section of the Charts page,
with durations on the y axis, to compare runs. The **Timing** tab of the run
details shows where one run's time went: each timer's calls, mean, p95, total
and share of the run, its duration over the epochs, and a timeline of one
epoch with a lane per rank.

**Timing callbacks without editing them.** A training framework that calls
callbacks from one loop can time every one of them by wrapping that call once:

```python
for cb in callbacks:
    with run.timer(f"callbacks/{type(cb).__name__}.{hook}", step=epoch,
                   accumulate=hook.endswith("_batch_end")):
        getattr(cb, hook)(trainer)
```

Hooks called on every batch accumulate, so they log one point per epoch after
a `flush()` (or at `finish()`).

**Example**

```python
import time

import nuboard as nb

run = nb.init("api-tour", run_name="timers")
data_wait = run.timer("data/wait", accumulate=True)

for epoch in range(5):
    with run.timer("train/epoch", step=epoch):
        for batch in range(20):
            with data_wait:
                time.sleep(0.001)  # waiting for the next batch

            time.sleep(0.002)  # forward and backward

        data_wait.flush(step=epoch)

    run.timer("val/epoch", step=epoch).start()
    time.sleep(0.01)
    run.timer("val/epoch").stop()

run.finish()
```
