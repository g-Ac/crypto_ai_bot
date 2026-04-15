"""ASCII chart generator for Pip-Boy dashboard.

Generates text-based equity curves and daily P&L bar charts
rendered as <pre> blocks in Jinja2 templates.
"""


def render_equity_curve(data: list[dict], width: int = 50) -> str:
    """Render an ASCII equity curve from cumulative P&L data.

    Args:
        data: List of {"day": "YYYY-MM-DD", "pnl": float}
        width: Chart width in columns
    """
    if not data:
        return "  [ NO DATA ]"

    if len(data) > width:
        step = len(data) / width
        sampled = [data[int(i * step)] for i in range(width)]
    else:
        sampled = data

    values = [d["pnl"] for d in sampled]
    vmin = min(values)
    vmax = max(values)

    if vmax == vmin:
        vmax = vmin + 1

    height = 8
    y_label_width = 8

    lines = []

    for row in range(height, -1, -1):
        y_val = vmin + (vmax - vmin) * row / height
        label = f"{y_val:>+7.0f}" if abs(y_val) >= 1 else f"{y_val:>+7.1f}"
        label = label[:y_label_width].rjust(y_label_width)

        chars = []
        for val in values:
            normalized = (val - vmin) / (vmax - vmin) * height
            if abs(normalized - row) < 0.5:
                chars.append("\u2022")
            elif normalized > row:
                chars.append("\u2502")
            else:
                chars.append(" ")
        lines.append(f"{label}|{''.join(chars)}")

    x_axis = " " * y_label_width + "+" + "\u2500" * len(values)
    lines.append(x_axis)

    if sampled:
        first = sampled[0]["day"][-5:]
        last = sampled[-1]["day"][-5:]
        padding = len(values) - len(first) - len(last)
        if padding > 0:
            x_labels = " " * (y_label_width + 1) + first + " " * padding + last
        else:
            x_labels = " " * (y_label_width + 1) + first
        lines.append(x_labels)

    return "\n".join(lines)


def render_daily_pnl(data: list[dict], width: int = 50) -> str:
    """Render ASCII bar chart of daily P&L.

    Args:
        data: List of {"day": "YYYY-MM-DD", "pnl": float}
        width: Max number of days to show
    """
    if not data:
        return "  [ NO DATA ]"

    recent = data[-width:] if len(data) > width else data
    values = [d["pnl"] for d in recent]

    abs_max = max(abs(v) for v in values) if values else 1
    if abs_max == 0:
        abs_max = 1

    bar_height = 6
    lines = []

    for row in range(bar_height, 0, -1):
        threshold = abs_max * row / bar_height
        chars = []
        for v in values:
            if v > 0 and v >= threshold:
                chars.append("\u2588")
            else:
                chars.append(" ")
        label = f"{threshold:>+7.0f}" if row == bar_height else " " * 7
        lines.append(f"{label} {''.join(chars)}")

    lines.append(f"{'0':>7} {''.join(['\u2500' for _ in values])}")

    for row in range(1, bar_height + 1):
        threshold = -abs_max * row / bar_height
        chars = []
        for v in values:
            if v < 0 and v <= threshold:
                chars.append("\u2588")
            else:
                chars.append(" ")
        label = f"{threshold:>+7.0f}" if row == bar_height else " " * 7
        lines.append(f"{label} {''.join(chars)}")

    wins = sum(1 for v in values if v > 0)
    losses = sum(1 for v in values if v < 0)
    avg = sum(values) / len(values) if values else 0
    lines.append(f"  AVG: ${avg:+.0f} | {wins}W {losses}L | DAYS: {len(values)}")

    return "\n".join(lines)
