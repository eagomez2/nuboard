# Distributed training

## Ranks

`init` reads the rank from `RANK` / `LOCAL_RANK` / `WORLD_SIZE` (torchrun),
falling back to `SLURM_PROCID` / `SLURM_LOCALID` / `SLURM_NTASKS` and
`OMPI_COMM_WORLD_RANK` / `OMPI_COMM_WORLD_SIZE`.

**Only rank 0 logs.** You can call `init` on every rank with the same
arguments; on other ranks `add_scalar()`, `add_text()` and the media calls
return immediately, so the same script runs unchanged on every rank:

```python
run = nb.init("llm", run_name="ddp", config=cfg)  # every rank
run.add_scalar({"train/loss": loss}, step=step)  # logged by rank 0 only
```

Or, as is usual with TensorBoard, create the run on rank 0 only:

```python
run = nb.init("llm", run_name="ddp", config=cfg) if rank == 0 else None

if run is not None:
    run.add_scalar({"train/loss": loss}, step=step)
```

`init` never waits for other ranks, so both patterns are safe. The only
difference: with rank 0 only, other machines of a multi-machine job record
no system metrics.

System metrics are the exception: local rank 0 of each machine samples
them, so a job on four machines records four sets of `system/` scalars. Each
rank that writes has its own `events.r<rank>.s<session>.log` (and
`media.r<rank>.pack`) in the run folder, so there is no contention and no
lock. Only rank 0 writes `run.json`.

## One folder for all ranks

All ranks must agree on the run folder. In order of preference:

1. With a shared job id, `TORCHELASTIC_RUN_ID` (set by torchrun with
   `--rdzv-id`) or `SLURM_JOB_ID`, the run id's random suffix is derived from
   it, and non-zero ranks wait (up to two minutes) for rank 0 to create the
   folder. Rank 0 never waits.
2. Without one, rank 0 picks a random id on its own and logs normally, and
   the other ranks do nothing: `run.id` is empty there. On one machine nothing
   is lost, since only rank 0 writes. On several machines, local rank 0 of each
   other machine warns that it cannot record its system metrics; pass
   `--rdzv-id` to torchrun to keep them.

Earlier versions broadcast rank 0's id through `torch.distributed`, which
hung the job when only rank 0 called `init` (issue #24).

## Viewing ranks

The viewer shows rank 0, as TensorBoard does. Other ranks' logs (timers
created with `all_ranks=True`, and each machine's system scalars) are read
from Python with `RunReader.scalars(..., rank=k)`, and timers of every rank
are compared in the run's **Timing** tab.

## Resume after preemption

Pass the run id (for example saved next to your checkpoint, or derived from
the job id) and `resume="auto"`:

```python
run = nb.init("llm", run_id=saved_run_id, resume="auto")
```

Each restart writes a new session file. Points from earlier sessions at steps
≥ the new session's first step are hidden, so restarting from a checkpoint
gives a clean curve.

## System scalars

The process with `LOCAL_RANK` 0 on each machine samples that machine's CPU,
memory and GPUs every 30 seconds and logs them under `system/`, in its own
rank's event log. A job on 4 machines with 8 GPUs each logs 4 sets, each with
8 GPUs. The viewer charts rank 0's machine; read another machine's with
`RunReader.scalars(..., rank=k)`. See
[System scalars](../api/init.md#system-scalars) for what is logged and how to
turn groups off.

## Timers

[Timers](../api/timer.md) are logged by rank 0 only, like scalars. To see how
the ranks differ (a slow rank makes the others wait at the next
synchronization), create a timer with `all_ranks=True`, or set
`nb.init(timing_all_ranks=True)` for every timer: each rank then logs its own
timings into its own event log, without any communication between ranks.
Never average timings across ranks inside the training loop with a collective
such as `all_reduce`: it adds a synchronization to every stop and hangs if a
rank skips a timer. The viewer aggregates the ranks instead.
