# Performance canvas

Write this only when presenting a performance finding for approval, and only after a full `hpcgate.py check` PASS. Read the canvas skill first and follow it. One `.canvas.tsx` per finding, at the workspace canvases directory the canvas skill names: `<workspace-canvases>/<finding-id-lower>-perf.canvas.tsx` (example: `f-012-spmv-perf.canvas.tsx`).

## Data

Use the latest `.agent/reports/gate-*.json`, field `stages.perf`. Ignore the report if `stages.perf.status` is not `PASS`.

Each row in `stages.perf.results` has `name`, `status` (`OK`, `IMPROVED`, `REGRESSION`, `NEW`, `REMOVED`), and, when both sides ran, `base_median`, `cand_median`, `rel_change`, `p_slower`. Medians from a `google-benchmark` config are seconds, lower is better. `rel_change` is `(candidate - base) / base` (negative means faster). `samples-json` values are in whatever unit the benchmark wrote; label that unit instead of assuming seconds.

Plot the benchmarks the finding names. If it names none, plot every row whose `status` is `IMPROVED` or `REGRESSION`, and say so in the caption. Omit rows that lack both medians.

Scale both series by the same factor so the axis is readable (`s`, `ms`, or `µs`). Do not scale one side only.

## Layout

Read `~/.cursor/skills-cursor/canvas/sdk/index.d.ts` before using a component. Import only from `cursor/canvas`. Embed the numbers in the file. No `fetch`.

- `H1`: the finding id and the kernel name.
- `Row` of `Stat`: the primary benchmark's percent change (`value` like `−18%`, `tone="success"` when faster, `tone="danger"` when slower) and the gate verdict. A third `Stat` only when another plotted benchmark regressed.
- `H2` "Median time by benchmark", then a grouped `BarChart`. `categories` are the benchmark names. Two series, `Base` (`tone="neutral"`) and `Candidate` (`tone="info"`). `valueSuffix` is the unit with a leading space. `showValues` when there are two series. `beginAtZero`.
- Caption under the chart, as `Text`: `Source: <report path> · <host> · <rounds> interleaved rounds · median, lower is better`.
- `Table` with headers Benchmark, Status, Base, Candidate, Change, p(slower). `columnAlign` right for the numeric columns. `rowTone` `success` for `IMPROVED`, `danger` for `REGRESSION`, omit otherwise. Change cells use a signed percent.

Do not add a section that has no rows. Do not invent a run that is not in the report.

In the approval message, link the canvas with its full absolute path, for example `[SpMV before and after](/absolute/path/f-012-spmv-perf.canvas.tsx)`.
