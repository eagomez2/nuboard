# Query language

The query bar filters, groups and orders runs. It is also available from
Python (`project.runs("…")`) and the command line (`nuboard ls -q "…"`).

```text
[where] CONDITION   [group by FIELD]   [agg AGG]   [order by FIELD [asc|desc]]   [limit N]
```

`where` is optional when the query starts with a condition.

## Examples

```text
where status != crashed order by started desc
where tags has "sweep" group by config.optim.lr agg mean±std
train/loss.min < 2.4 order by train/loss.min limit 10
config.lr in (1e-3, 3e-4) and not archived = true
name ~ "^lr1e-3"
where project = "vit-ablations" group by config.augment agg min-max
eval/acc exists
```

## Fields

| Field | Meaning |
| --- | --- |
| `name`, `id`, `project`, `path`, `group` | identity |
| `status` | `running`, `finished`, `crashed`, `killed`, `lost` |
| `tags`, `notes`, `starred`, `archived`, `reviewed` | from `init` and the viewer |
| `created`, `started`, `ended`, `duration` | Unix seconds / seconds |
| `host`, `commit`, `world_size` | environment |
| `collections` | the collections a run belongs to: `collections has "shortlist"` |
| `alerts` | number of [health alerts](../guide/alerts.md): `alerts > 0` |
| `fields.<name>` | a property set in the viewer, e.g. `fields.verdict = keep` |
| `config.<dotted.key>` | any config value, e.g. `config.optim.lr` |
| `<key>` | a top-level config key, e.g. `lr`, or else a property, e.g. `verdict` (when no other field matches) |
| `<scalar>.<stat>` | summary of a scalar: `last`, `min`, `max`, `count`, `step`, `nonfinite`, e.g. `train/loss.min` |
| `<scalar>` | shorthand for `<scalar>.last` |

## Operators

| Operator | Meaning |
| --- | --- |
| `=`, `==`, `!=` | equality (numbers numerically, text case-insensitively) |
| `<`, `<=`, `>`, `>=` | ordering |
| `~`, `!~` | regular expression match (case-insensitive) |
| `has` | list membership (`tags has "sweep"`), or substring for text |
| `in (a, b, …)`, `not in (…)` | one of several values |
| `exists` | the field is present |
| `and`, `or`, `not`, `( … )` | combine conditions (`and` binds tighter than `or`) |

Values are numbers (`1e-3`), quoted strings (`"sweep"`, `'x'`), bare words
(`crashed`), or `true`, `false`, `null`.

## Grouping and aggregation

`group by FIELD` sets how the Charts page groups runs. `agg` picks the band:

| `agg` | Line | Band |
| --- | --- | --- |
| `mean±std` (default) | mean | ± one standard deviation |
| `mean±sem` | mean | ± standard error |
| `min-max` | mean | min to max |
| `median` | median | min to max |
| `mean` | mean | none |

`order by` and `limit` apply to the Runs page and to `nuboard ls`.
