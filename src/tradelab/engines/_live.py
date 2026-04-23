"""Live terminal progress for long-running engines.

Two pieces:

  * :class:`LiveOptunaProgress` — a Rich progress bar that doubles as an Optuna
    callback. Shows trial X/N, elapsed + ETA, running best fitness. Use as a
    context manager and pass the instance to ``study.optimize(callbacks=[p])``.

  * :func:`print_trials_chart` / :func:`print_wf_chart` — plotext ASCII charts
    rendered at the end of an optimize or walk-forward run, so the terminal
    keeps a compact record of what just happened.

Neither piece requires a TTY: Rich Progress falls back to simple text when
stdout is not a terminal, and plotext renders as ASCII either way.
"""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


class LiveOptunaProgress:
    """Context-managed Rich progress that is also an Optuna study callback."""

    def __init__(
        self,
        total: int,
        description: str = "Optimizing",
        console: Optional[Console] = None,
    ):
        self.total = total
        self.description = description
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("best=[bold green]{task.fields[best]}[/bold green]"),
            TextColumn("trial=[dim]{task.fields[last]}[/dim]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
            refresh_per_second=4,
        )
        self.task_id = None

    def __enter__(self) -> "LiveOptunaProgress":
        self.progress.__enter__()
        self.task_id = self.progress.add_task(
            self.description, total=self.total, best="n/a", last="—",
        )
        return self

    def __exit__(self, *exc):
        self.progress.__exit__(*exc)

    def __call__(self, study, trial) -> None:
        """Optuna callback protocol — study.optimize(callbacks=[self])."""
        try:
            best = study.best_value
        except ValueError:
            best = None
        pf = trial.user_attrs.get("pf")
        tr = trial.user_attrs.get("trades")
        last_desc = (
            f"#{trial.number} pf={pf:.2f} tr={tr}"
            if pf is not None and tr is not None
            else f"#{trial.number}"
        )
        self.progress.update(
            self.task_id,
            advance=1,
            best=f"{best:.3f}" if best is not None else "n/a",
            last=last_desc,
        )


def _safe_plotext_show(plt) -> None:
    """Call plt.show() but swallow UnicodeEncodeError — happens when stdout is
    a cp1252 pipe (piped output on Windows) and plotext emits box-drawing
    chars. In a real UTF-8 terminal, the chart renders fine."""
    try:
        plt.show()
    except UnicodeEncodeError:
        # Fall back to no chart rather than crashing the whole run.
        import sys
        sys.stderr.write(
            "[plotext: terminal chart skipped — stdout encoding doesn't "
            "support Unicode box-drawing chars]\n"
        )


def print_trials_chart(study, title: str = "Optuna trial fitness") -> None:
    """Render an ASCII plot of per-trial fitness + running best."""
    try:
        import plotext as plt
    except ImportError:
        return

    values: list[float] = []
    for t in study.trials:
        if t.value is None:
            continue
        values.append(float(t.value))
    if len(values) < 2:
        return

    running_best: list[float] = []
    cur = float("-inf")
    for v in values:
        cur = max(cur, v)
        running_best.append(cur)

    xs = list(range(1, len(values) + 1))
    plt.clf()
    plt.theme("pro")
    plt.plot(xs, values, label="per-trial", color="cyan", marker="dot")
    plt.plot(xs, running_best, label="running best", color="green")
    plt.title(title)
    plt.xlabel("trial #")
    plt.ylabel("fitness")
    plt.plotsize(80, 18)
    _safe_plotext_show(plt)


def print_wf_chart(wf_result, title: str = "Walk-forward: IS vs OOS PF") -> None:
    """Render an ASCII bar chart of per-window IS vs OOS profit factor."""
    try:
        import plotext as plt
    except ImportError:
        return

    labels: list[str] = []
    is_pf: list[float] = []
    oos_pf: list[float] = []
    for w in wf_result.windows:
        if w.train_metrics is None or w.test_metrics is None:
            continue
        labels.append(f"w{w.index + 1}")
        is_pf.append(float(min(w.train_metrics.profit_factor, 10.0)))
        oos_pf.append(float(min(w.test_metrics.profit_factor, 10.0)))
    if not labels:
        return

    plt.clf()
    plt.theme("pro")
    plt.multiple_bar(labels, [is_pf, oos_pf], labels=["IS", "OOS"])
    plt.title(title)
    plt.ylabel("PF (capped at 10)")
    plt.plotsize(80, 16)
    _safe_plotext_show(plt)
