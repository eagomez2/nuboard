# Distributed training

## Ranks

`init` reads the rank from `RANK` / `LOCAL_RANK` / `WORLD_SIZE` (torchrun),
falling back to `SLURM_PROCID` / `SLURM_LOCALID` / `SLURM_NTASKS` and
`OMPI_COMM_WORLD_RANK` / `OMPI_COMM_WORLD_SIZE`.

Call `init` on every rank with the same arguments. **Only rank 0 logs by
default**; on other ranks `log()` returns immediately. To record a metric on
every rank (gradient norms, throughput, memory), pass `all_ranks=True` to that
call, or to `init` to make it the default:

```python
run = nb.init("llm", name="ddp", config=cfg)  # every rank
run.log({"train/loss": loss}, step=step)  # rank 0 only
run.log({"sys/tokens_per_sec": tps}, step=step, all_ranks=True)
```

Each rank writes its own `events.r<rank>.s<session>.log` (and
`media.r<rank>.pack`) in the same run folder, so there is no contention and no
lock. Only rank 0 writes `run.json`.

## One folder for all ranks

All ranks must agree on the run folder. In order of preference:

1. If `torch.distributed` is initialized when `init` runs, rank 0's run id is
   broadcast to the other ranks.
2. Otherwise a shared job id is used: `TORCHELASTIC_RUN_ID` (set by torchrun
   with `--rdzv-id`) or `SLURM_JOB_ID`. The run id's random suffix is derived
   from it, and non-zero ranks wait (up to two minutes) for rank 0 to create
   the folder.
3. Without either, non-zero ranks cannot find rank 0's folder: they log
   nothing and emit a warning saying why. Rank 0 logs normally.

## Viewing ranks

The viewer and `RunReader` show rank 0 by default; `RunReader.scalars(...,
rank=k)` reads another rank. A rank-0 line with min/mean/max bands across ranks
is on the [roadmap](../roadmap.md).

## Resume after preemption

Pass the run id (for example saved next to your checkpoint, or derived from
the job id) and `resume="auto"`:

```python
run = nb.init("llm", run_id=saved_run_id, resume="auto")
```

Each restart writes a new session file. Points from earlier sessions at steps
≥ the new session's first step are hidden, so restarting from a checkpoint
gives a clean curve.

## System metrics

Per-node GPU metrics via NVML (collected by `LOCAL_RANK 0`) are not
implemented in 0.1; log them yourself with `all_ranks=True` meanwhile.
