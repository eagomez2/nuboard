# `finish`, `flush` and `summary`

## `finish`

```python
run.finish(status="finished", *, exit_code=0, error=None)
```

Flushes, writes an end frame, records the status, exit code and end time in
`run.json`, and compacts the logs into `data.parquet` when PyArrow is
installed. It is safe to call twice.

- It is called at interpreter exit, and when a `with` block ends.
- An uncaught exception marks the run `crashed` and stores the traceback as
  `exit.error`. `KeyboardInterrupt` marks it `killed`.
- If the process is killed outright (SIGKILL, the OOM killer), everything
  flushed so far stays readable. The run keeps the status `running`, and the
  viewer shows it as **lost** once its heartbeat is two minutes old.


## `finished`

```python
run.finished  # True once finish() has run
```

A read-only property, also True for the no-op run that ranks other than 0 get
when they cannot find rank 0's run. The [framework
integrations](../guide/integrations.md) use it to resume a run that was
finished, such as for a test after a fit.

## `flush`

```python
run.flush()
```

Waits until everything logged so far is on disk. You rarely need it: the
background thread writes every `flush_interval` seconds, and `finish` flushes.


## `summary`

A dict of the run's scalars so far. Each one maps to `last`, `step`, `min`,
`max`, `count` and `nonfinite`. It is empty until something has been logged.

```python
run.summary["train/loss"]["min"]
```
