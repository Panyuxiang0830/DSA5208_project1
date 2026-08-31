from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_DIR = PROJECT_ROOT / "results" / "summary"
FIGURE_DIR = PROJECT_ROOT / "results" / "figures"

CONFIGS = ["C1", "C2", "C3", "C4"]
MODELS = [
    "read-your-writes",
    "monotonic-reads",
    "monotonic-writes",
    "writes-follow-reads",
]
MODEL_LABELS = ["RYW", "MR", "MW", "WFR"]
PHASES = ["pre-fault", "election", "post-election"]
PHASE_LABELS = ["Pre-fault", "Election", "Post-election"]

BLUE = "#3568C0"
ORANGE = "#D97706"
TEAL = "#16867A"
RED = "#C2413B"
GRID = "#D7DCE2"
MUTED = "#5D6672"


def load_one(pattern: str) -> dict[str, Any]:
    matches = sorted(SUMMARY_DIR.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one match for {pattern!r}, found {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def load_many(pattern: str) -> list[dict[str, Any]]:
    matches = sorted(SUMMARY_DIR.glob(pattern))
    if not matches:
        raise RuntimeError(f"No matches for {pattern!r}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in matches]


def save_figure(figure: plt.Figure, stem: str) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = FIGURE_DIR / f"{stem}.svg"
    figure.savefig(
        FIGURE_DIR / f"{stem}.png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )
    figure.savefig(
        svg_path,
        bbox_inches="tight",
        facecolor="white",
    )
    # Matplotlib formats multi-line SVG path data with trailing spaces.
    # Normalise generated text so repository whitespace checks stay clean.
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_text.splitlines()) + "\n",
        encoding="utf-8",
    )
    plt.close(figure)


def aggregate_groups(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, int]]:
    aggregate: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"checks": 0, "violations": 0, "errors": 0}
    )
    for group in summary["groups"]:
        key = (str(group["config_id"]), str(group["model"]))
        aggregate[key]["checks"] += int(group["check_count"])
        aggregate[key]["violations"] += int(group["violation_count"])
        aggregate[key]["errors"] += int(group["error_count"])
    return aggregate


def violation_matrix(summary: dict[str, Any]) -> np.ndarray:
    aggregate = aggregate_groups(summary)
    matrix = np.full((len(CONFIGS), len(MODELS)), np.nan)
    for row, config in enumerate(CONFIGS):
        for column, model in enumerate(MODELS):
            group = aggregate.get((config, model))
            if group and group["checks"]:
                matrix[row, column] = 100 * group["violations"] / group["checks"]
    return matrix


def make_consistency_matrix() -> None:
    scenarios = [
        ("S0 Normal", load_one("baseline-s0-formal-*.summary.json")),
        ("S1 Secondary stopped", load_one("s1-secondary-failure-formal-*.summary.json")),
        ("S2 Primary stopped", load_one("s2-primary-failure-formal-*.summary.json")),
        (
            "S3 Primary partitioned",
            load_one("s3-primary-partition-formal-rerun-*.summary.json"),
        ),
        (
            "S4 Replication paused",
            load_one("s4-secondary-replication-lag-formal-*.summary.json"),
        ),
    ]
    color_map = LinearSegmentedColormap.from_list(
        "violation-rate", ["#F3F7FC", "#75A7DF", "#163B70"]
    )
    color_map.set_bad("#E5E7EB")

    figure, axes = plt.subplots(2, 3, figsize=(10.5, 6.6), constrained_layout=True)
    images = []
    for axis, (title, summary) in zip(axes.flat, scenarios, strict=False):
        matrix = violation_matrix(summary)
        image = axis.imshow(matrix, vmin=0, vmax=100, cmap=color_map, aspect="auto")
        images.append(image)
        axis.set_title(title, fontweight="bold", pad=8)
        axis.set_xticks(range(len(MODEL_LABELS)), MODEL_LABELS)
        axis.set_yticks(range(len(CONFIGS)), CONFIGS)
        axis.set_xlabel("Client-centric model")
        axis.set_ylabel("Configuration")
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = matrix[row, column]
                if np.isnan(value):
                    label = "not tested"
                    color = MUTED
                else:
                    label = f"{value:.1f}%"
                    color = "white" if value >= 45 else "#111827"
                axis.text(
                    column,
                    row,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=color,
                )
        for spine in axis.spines.values():
            spine.set_visible(False)

    axes.flat[-1].axis("off")
    axes.flat[-1].text(
        0.02,
        0.72,
        "Violation rate\nviolations / successful checks",
        fontsize=11,
        fontweight="bold",
        va="top",
    )
    axes.flat[-1].text(
        0.02,
        0.45,
        "S4 intentionally tests C3 only.\nGrey cells were not run.",
        fontsize=9,
        color=MUTED,
        va="top",
    )
    color_bar = figure.colorbar(images[0], ax=axes, location="bottom", shrink=0.55, pad=0.04)
    color_bar.set_label("Violation rate (%)")
    color_bar.set_ticks([0, 25, 50, 75, 100])
    figure.suptitle(
        "Client-centric consistency violations across scenarios",
        fontsize=14,
        fontweight="bold",
    )
    save_figure(figure, "01_consistency_violation_matrix")


def aggregate_transition(
    summaries: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, int]]]:
    aggregate: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(
            lambda: {"operations": 0, "checks": 0, "violations": 0, "errors": 0}
        )
    )
    for summary in summaries:
        for row in summary["phase_rows"]:
            phase = str(row["phase"])
            config = str(row["config_id"])
            aggregate[phase][config]["operations"] += int(row["operation_count"])
            aggregate[phase][config]["checks"] += int(row["check_count"])
            aggregate[phase][config]["violations"] += int(row["violation_count"])
            aggregate[phase][config]["errors"] += int(row["error_count"])
    return aggregate


def make_transition_outcomes() -> None:
    scenario_data = [
        (
            "T1 Primary stopped",
            BLUE,
            aggregate_transition(
                load_many("t1-primary-stop-transition-formal-rerun-*.summary.json")
            ),
        ),
        (
            "T2 Primary partitioned",
            ORANGE,
            aggregate_transition(
                load_many("t2-primary-partition-transition-formal-rerun-*.summary.json")
            ),
        ),
    ]
    x_positions = np.arange(len(PHASES))
    width = 0.34
    figure, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), constrained_layout=True)

    for scenario_index, (label, color, aggregate) in enumerate(scenario_data):
        violation_rates = []
        error_rates = []
        for phase in PHASES:
            c3 = aggregate[phase]["C3"]
            violation_rates.append(100 * c3["violations"] / c3["checks"])
            totals = {
                metric: sum(aggregate[phase][config][metric] for config in CONFIGS)
                for metric in ("operations", "errors")
            }
            error_rates.append(100 * totals["errors"] / totals["operations"])

        offsets = x_positions + (scenario_index - 0.5) * width
        bars = axes[0].bar(offsets, violation_rates, width, color=color, label=label)
        axes[0].bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8)
        error_bars = axes[1].bar(offsets, error_rates, width, color=color, label=label)
        axes[1].bar_label(error_bars, fmt="%.2f%%", padding=3, fontsize=8)

    axes[0].set_title("C3 read-your-writes violations", fontweight="bold")
    axes[0].set_ylabel("Violation rate (%)")
    axes[0].set_ylim(0, 90)
    axes[0].text(
        0.02,
        0.97,
        "C1, C2 and C4: 0 violations in every phase",
        transform=axes[0].transAxes,
        va="top",
        fontsize=8,
        color=MUTED,
    )
    axes[1].set_title("Temporary operation errors", fontweight="bold")
    axes[1].set_ylabel("Error rate (%)")
    axes[1].set_ylim(0, 2.4)

    for axis in axes:
        axis.set_xticks(x_positions, PHASE_LABELS)
        axis.grid(axis="y", color=GRID, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, loc="lower center", bbox_to_anchor=(1.1, -0.28), ncol=2)
    figure.suptitle(
        "Election-window consistency and availability",
        fontsize=14,
        fontweight="bold",
    )
    save_figure(figure, "02_transition_window_outcomes")


def read_timing_rows() -> list[dict[str, str]]:
    path = SUMMARY_DIR / "extended_fault_timings.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def make_fault_timing() -> None:
    rows = read_timing_rows()
    election_labels = ["T1 Primary\nstopped", "T2 Primary\npartitioned"]
    election_lookup = {
        "T1 Primary stopped": [],
        "T2 Primary partitioned": [],
    }
    replication: dict[str, float] = {}
    for row in rows:
        seconds = float(row["value_ms"]) / 1000
        if row["metric_group"] == "election":
            election_lookup[row["scenario"]].append(seconds)
        else:
            replication[row["metric"]] = seconds

    figure, axes = plt.subplots(1, 2, figsize=(9.6, 4.2), constrained_layout=True)
    jitter = np.array([-0.08, 0.0, 0.08])
    colors = [BLUE, ORANGE]
    for index, (scenario, values) in enumerate(election_lookup.items()):
        values_array = np.array(values)
        axes[0].scatter(
            np.full(len(values_array), index) + jitter[: len(values_array)],
            values_array,
            s=55,
            color=colors[index],
            edgecolor="white",
            linewidth=0.8,
            zorder=3,
        )
        mean_value = float(values_array.mean())
        axes[0].hlines(mean_value, index - 0.19, index + 0.19, color="#111827", linewidth=2)
        axes[0].text(index, mean_value + 0.8, f"mean {mean_value:.1f}s", ha="center", fontsize=8)
    axes[0].set_xticks([0, 1], election_labels)
    axes[0].set_ylabel("Election duration (seconds)")
    axes[0].set_ylim(0, 20)
    axes[0].set_title("Primary replacement election", fontweight="bold")
    axes[0].grid(axis="y", color=GRID, linewidth=0.7)

    timing_labels = ["Lag at workload end", "Catch-up duration"]
    timing_values = [
        replication["lag at workload end"],
        replication["catch-up duration"],
    ]
    bars = axes[1].barh(timing_labels, timing_values, color=[RED, TEAL], height=0.52)
    axes[1].bar_label(bars, fmt="%.1fs", padding=4, fontsize=9)
    axes[1].invert_yaxis()
    axes[1].set_xlim(0, 43)
    axes[1].set_xlabel("Seconds")
    axes[1].set_title("S4 replication lag and recovery", fontweight="bold")
    axes[1].grid(axis="x", color=GRID, linewidth=0.7)
    for axis in axes:
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle("Fault timing measurements", fontsize=14, fontweight="bold")
    save_figure(figure, "03_fault_timing")


def make_s4_model_rates() -> None:
    summary = load_one("s4-secondary-replication-lag-formal-*.summary.json")
    aggregate = aggregate_groups(summary)
    labels = ["Read-your-writes", "Monotonic reads", "Monotonic writes", "Writes-follow-reads"]
    rates = []
    counts = []
    for model in MODELS:
        group = aggregate[("C3", model)]
        rates.append(100 * group["violations"] / group["checks"])
        counts.append(f"{group['violations']:,} / {group['checks']:,}")

    figure, axis = plt.subplots(figsize=(8.2, 4.2), constrained_layout=True)
    y_positions = np.arange(len(labels))
    bars = axis.barh(y_positions, rates, color=BLUE, height=0.56)
    axis.set_yticks(y_positions, labels)
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.set_xlabel("Violation rate (%)")
    axis.set_title(
        "C3 under a readable but replication-paused Secondary",
        fontsize=13,
        fontweight="bold",
        pad=10,
    )
    axis.grid(axis="x", color=GRID, linewidth=0.7)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    for bar, rate, count in zip(bars, rates, counts, strict=True):
        axis.text(
            min(rate + 2, 93),
            bar.get_y() + bar.get_height() / 2,
            f"{rate:.1f}%  ({count})",
            va="center",
            fontsize=9,
            color="#111827",
        )
    axis.text(
        0.0,
        -0.18,
        "500 sequences × 3 seeds; MW is one final-order validation per seed",
        transform=axis.transAxes,
        fontsize=8,
        color=MUTED,
    )
    save_figure(figure, "04_s4_model_violation_rates")


def main() -> int:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.transparent": False,
        }
    )
    make_consistency_matrix()
    make_transition_outcomes()
    make_fault_timing()
    make_s4_model_rates()
    print(f"Wrote report figures to {FIGURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
