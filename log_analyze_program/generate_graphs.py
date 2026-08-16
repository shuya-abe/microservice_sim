import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import argparse
import os
from matplotlib.lines import Line2D
# import japanize_matplotlib # Removed for English-only output

plt.ioff()

# Legend ordering policy:
# - Set to "first" to place serverless series first.
# - Set to "last" to place serverless series last.
SERVERLESS_LEGEND_POSITION = "last"
# Trade-off axis mode:
# - "linear": only linear axes
# - "log": x linear + y log axes
# - "both": generate both linear and x-linear/y-log variants
TRADEOFF_AXIS_MODE = "both"
# Prefer total metrics on trade-off Y axis if available.
TRADEOFF_USE_TOTAL_METRICS = True
TRADEOFF_ADD_PER_TIME_METRICS = True
TRADEOFF_ADD_LEFT_INSET = True
TRADEOFF_ADD_BROKEN_X = True
LEGEND_HANDLE_LENGTH = 4.0


def _legend_sort_key(key_tuple):
    instance_type, cpu_val = key_tuple
    itype = str(instance_type).lower()
    is_serverless = itype.startswith('serverless')
    is_container = itype.startswith('container')
    is_warm_wait = ('warm_wait' in itype) or itype.endswith('_wait')

    if SERVERLESS_LEGEND_POSITION == "first":
        serverless_rank = 0 if is_serverless else 1
    else:
        serverless_rank = 1 if is_serverless else 0

    # container → serverless → serverless_warm_wait → other
    if is_container:
        type_rank = 0
    elif is_serverless and not is_warm_wait:
        type_rank = 1
    elif is_warm_wait:
        type_rank = 2
    else:
        type_rank = 3

    try:
        cpu_rank = float(cpu_val)
    except (TypeError, ValueError):
        cpu_rank = float('inf')

    return (serverless_rank, type_rank, cpu_rank, str(instance_type))


def _pareto_frontier_minimize(df, x_col, y_col):
    """
    Returns Pareto-optimal points for 2D minimization (x and y both lower is better).
    """
    if df.empty:
        return df

    pareto_candidates = df[[x_col, y_col]].dropna().copy()
    if pareto_candidates.empty:
        return pareto_candidates

    pareto_candidates = pareto_candidates.sort_values(by=[x_col, y_col], ascending=[True, True])
    best_y = float('inf')
    keep_indices = []

    for idx, row in pareto_candidates.iterrows():
        y_val = row[y_col]
        if y_val < best_y:
            keep_indices.append(idx)
            best_y = y_val

    frontier = pareto_candidates.loc[keep_indices].drop_duplicates(subset=[x_col, y_col])
    return frontier.sort_values(by=x_col)


def _is_positive_series(series):
    if series.empty:
        return False
    return bool((series > 0).all())


def _compute_x_focus_ranges(x_series):
    """
    Detects a left-cluster and returns x-limits for left-zoom inset and broken-x plots.
    Uses the largest multiplicative gap x[i+1]/x[i] on sorted positive unique x values.
    """
    xs = sorted(float(v) for v in pd.Series(x_series).dropna().unique() if float(v) > 0)
    if len(xs) < 2:
        return None

    gap_pairs = []
    n = len(xs)
    min_side_points = max(2, int(round(n * 0.15)))
    min_side_points = min(min_side_points, max(2, n // 2))

    for i in range(len(xs) - 1):
        if xs[i] <= 0:
            continue
        left_count = i + 1
        right_count = n - (i + 1)
        if left_count < min_side_points or right_count < min_side_points:
            continue
        gap_pairs.append((xs[i + 1] / xs[i], i))

    # Fallback: if constraints are too strict for small n, use all valid gaps.
    if not gap_pairs:
        for i in range(len(xs) - 1):
            if xs[i] > 0:
                gap_pairs.append((xs[i + 1] / xs[i], i))
    if not gap_pairs:
        return None

    max_ratio, split_idx = max(gap_pairs, key=lambda t: t[0])

    # If no obvious multiplicative jump exists, split near 40th percentile for readability.
    if max_ratio < 1.4 and len(xs) >= 4:
        split_idx = max(0, int(round((len(xs) - 1) * 0.4)))
        split_idx = min(split_idx, len(xs) - 2)
        max_ratio = xs[split_idx + 1] / xs[split_idx] if xs[split_idx] > 0 else float('inf')

    left_values = xs[:split_idx + 1]
    right_values = xs[split_idx + 1:]
    left_min = left_values[0]
    left_max = left_values[-1]
    right_min = right_values[0]
    right_max = right_values[-1]

    total_span = max(right_max - left_min, max(abs(right_max) * 0.02, 1e-12))
    left_span = max(left_max - left_min, max(abs(left_max) * 0.05, 1e-12))
    right_span = max(right_max - right_min, max(abs(right_max) * 0.05, 1e-12))

    # Keep inset tight around the left cluster (avoid total-span-dominated padding).
    left_pad_left = max(left_span * 0.10, abs(left_min) * 0.01, 1e-12)
    left_pad_right = max(left_span * 0.10, abs(left_max) * 0.01, 1e-12)
    right_pad = max(right_span * 0.15, total_span * 0.02)

    left_xlim = (max(0.0, left_min - left_pad_left), left_max + left_pad_right)
    right_xlim = (max(0.0, right_min - right_pad), right_max + right_pad)

    # Safety: left inset must include the minimum x and the left cluster upper point.
    left_xlim = (min(left_xlim[0], left_min), max(left_xlim[1], left_max))

    if right_xlim[0] <= left_xlim[1]:
        split_gap = right_min - left_max
        if split_gap <= 0:
            return None
        # Keep both windows separated while preserving representative edge points.
        left_upper = left_max + split_gap * 0.4
        right_lower = right_min - split_gap * 0.4
        left_xlim = (left_xlim[0], max(left_upper, left_max))
        right_xlim = (max(0.0, min(right_lower, right_min)), right_xlim[1])

    if right_xlim[0] <= left_xlim[1]:
        return None

    return {
        'left_xlim': left_xlim,
        'right_xlim': right_xlim,
        'split_ratio': max_ratio,
    }


def _plot_tradeoff_series(
    ax,
    variant_df,
    x_col,
    y_col,
    axis_mode,
    color_map,
    linestyle_map,
    marker_map,
    include_labels=True,
    annotate_lambda_endpoints=True,
):
    grouped = variant_df.groupby(['instance_type', 'CPU'], sort=False)
    grouped_items = sorted(grouped, key=lambda item: _legend_sort_key(item[0]))

    lines_plotted = 0
    for (instance_type, cpu_val), group_data in grouped_items:
        series = group_data.sort_values(by='lambda')
        if series.empty:
            continue

        if axis_mode == "log" and (not _is_positive_series(series[y_col])):
            continue

        plot_color = color_map[(instance_type, cpu_val)]
        plot_linestyle = linestyle_map.get(instance_type, '-')
        plot_marker = marker_map.get(instance_type, '.')
        series_label = f"{instance_type}, CPU={int(cpu_val) if float(cpu_val).is_integer() else cpu_val}"
        line_label = series_label if include_labels else '_nolegend_'

        ax.plot(
            series[x_col],
            series[y_col],
            marker=plot_marker,
            linestyle=plot_linestyle,
            color=plot_color,
            label=line_label,
        )

        min_lambda_idx = series['lambda'].idxmin()
        max_lambda_idx = series['lambda'].idxmax()

        min_row = series.loc[min_lambda_idx]
        max_row = series.loc[max_lambda_idx]

        ax.scatter(
            min_row[x_col],
            min_row[y_col],
            marker='*',
            s=72,
            color=plot_color,
            edgecolors='black',
            linewidths=1.0,
            zorder=4,
        )
        ax.scatter(
            max_row[x_col],
            max_row[y_col],
            marker='D',
            s=72,
            color=plot_color,
            edgecolors='black',
            linewidths=1.0,
            zorder=4,
        )

        if annotate_lambda_endpoints:
            ax.annotate(
                f"λmin={min_row['lambda']:.3g}",
                (min_row[x_col], min_row[y_col]),
                xytext=(5, 6),
                textcoords='offset points',
                fontsize=8,
                color=plot_color,
            )
            ax.annotate(
                f"λmax={max_row['lambda']:.3g}",
                (max_row[x_col], max_row[y_col]),
                xytext=(5, -10),
                textcoords='offset points',
                fontsize=8,
                color=plot_color,
            )

        lines_plotted += 1

    return lines_plotted


def _endpoint_legend_handles():
    return [
        Line2D(
            [0], [0], marker='*', color='none', markerfacecolor='gray',
            markeredgecolor='black', markersize=8, label='min lambda in series'
        ),
        Line2D(
            [0], [0], marker='D', color='none', markerfacecolor='gray',
            markeredgecolor='black', markersize=8, label='max lambda in series'
        ),
    ]

def plot_graphs(csv_filepath):
    """
    Generates graphs from a processed CSV file with specified styling,
    including different markers per instance_type and integer X-axis ticks.
    All labels and messages are in English.
    Y-axis limits are now configurable per plot type.
    """
    # 1. Read CSV
    try:
        df = pd.read_csv(csv_filepath)
    except FileNotFoundError:
        print(f"Error: File not found at {csv_filepath}")
        return
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return

    # 2. Validate required columns
    required_cols = [
        'mu', 'CPU', 'instance_type', 'lambda',
        'ave_total_50', 'ave_wait_50', 'ave_service_50',
        'cost_per_time_50', 'energy_per_time_wh_per_sec_50',
        'cost_per_request_50', 'energy_per_request_wh_50',
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"Error: CSV file '{csv_filepath}' is missing required columns: {', '.join(missing_cols)}")
        return

    numeric_plot_cols = [
        'mu', 'CPU', 'lambda',
        'ave_total_50', 'ave_wait_50', 'ave_service_50',
        'cost_per_time_50', 'energy_per_time_wh_per_sec_50',
        'cost_per_request_50', 'energy_per_request_wh_50',
        'total_cost_50', 'total_energy_wh_50',
        'ave_instances_50',
    ]
    for col in numeric_plot_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df.dropna(subset=['mu', 'CPU', 'instance_type', 'lambda'], inplace=True)

    if df.empty:
        print("No valid data available after initial cleaning and type conversion.")
        return

    # 3. Get unique mu values and sort them
    unique_mus = sorted(df['mu'].unique())

    # 4. Plot config: split by mu and metric, X axis is always lambda.
    plot_types_config = {
        'total': {'col': 'ave_total_50', 'label': 'ave. of Total time [s]'},
        'wait': {'col': 'ave_wait_50', 'label': 'ave. of Wait time [s]'},
        'service': {'col': 'ave_service_50', 'label': 'ave. of Service time [s]'},
        'instances': {
            'col': 'ave_instances_50',
            'label': 'ave. of Hot Instances',
        },
        'cost_per_time': {
            'col': 'cost_per_time_50',
            'label': 'Cost per Time [USD/s]',
        },
        'energy_per_time': {
            'col': 'energy_per_time_wh_per_sec_50',
            'label': 'Energy per Time [Wh/s]',
        },
        'cost_per_request': {
            'col': 'cost_per_request_50',
            'label': 'Cost per Request [USD/req]',
        },
        'energy_per_request': {
            'col': 'energy_per_request_wh_50',
            'label': 'Energy per Request [Wh/req]',
        },
    }

    # Pre-split by mu once to avoid repeatedly filtering full DataFrame.
    mu_frames = {mu_val: df[df['mu'] == mu_val].copy() for mu_val in unique_mus}

    # 5. Loop for each mu value
    for mu_val in unique_mus:
        print(f"\nProcessing graphs for mu = {mu_val}...")
        df_mu_filtered = mu_frames[mu_val]

        if df_mu_filtered.empty:
            print(f"No data found for mu = {mu_val}.")
            continue

        # --- Style setup ---
        unique_instance_types = sorted(df_mu_filtered['instance_type'].unique())
        unique_series = sorted(
            df_mu_filtered[['instance_type', 'CPU']]
            .dropna()
            .drop_duplicates()
            .itertuples(index=False, name=None),
            key=_legend_sort_key,
        )
        unique_cpus = sorted(df_mu_filtered['CPU'].dropna().unique())

        try:
            # Combine categorical palettes to keep instance/CPU series visually distinct.
            available_colors = (
                list(plt.colormaps['tab20'].colors)
                + list(plt.colormaps['tab20b'].colors)
                + list(plt.colormaps['tab20c'].colors)
            )
        except AttributeError:
            try:
                available_colors = (
                    list(plt.cm.get_cmap('tab20').colors)
                    + list(plt.cm.get_cmap('tab20b').colors)
                    + list(plt.cm.get_cmap('tab20c').colors)
                )
            except AttributeError:
                 available_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                                     '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'] # Fallback list

        if not hasattr(available_colors, '__iter__') or not available_colors or len(available_colors) < 1: # Final check for safety
             available_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                                 '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']


        color_map = {
            series_key: available_colors[i % len(available_colors)]
            for i, series_key in enumerate(unique_series)
        }
        cpu_index_map = {cpu_val: idx for idx, cpu_val in enumerate(unique_cpus)}

        available_linestyles = ['-', '--', ':', '-.']
        available_markers = ['o', 's', '^', 'D', 'v', 'p', '*', 'X']

        linestyle_map = {
            itype: available_linestyles[i % len(available_linestyles)]
            for i, itype in enumerate(unique_instance_types)
        }
        marker_map = {
            itype: available_markers[i % len(available_markers)]
            for i, itype in enumerate(unique_instance_types)
        }
        # --- Style setup complete ---

        # 6. Loop for each plot type
        for plot_key, config_item in plot_types_config.items():
            y_col_name = config_item['col']
            y_axis_label = config_item['label']

            if y_col_name not in df_mu_filtered.columns:
                print(f"Skipping mu={mu_val}, type='{plot_key}' because column '{y_col_name}' is absent.")
                continue

            if df_mu_filtered[y_col_name].isnull().all():
                print(f"Skipping mu={mu_val}, type='{plot_key}' because all '{y_col_name}' values are NaN or missing.")
                continue

            plt.figure(figsize=(12, 7))
            ax = plt.gca()

            plot_df = df_mu_filtered[['lambda', 'instance_type', 'CPU', y_col_name]].copy()
            plot_df = plot_df.dropna(subset=['lambda', 'instance_type', 'CPU', y_col_name])
            # X axis uses lambda values only; keep zero/near-zero Y values for visibility.
            plot_df = plot_df[plot_df['lambda'] > 0]

            if plot_df.empty:
                print(f"Skipping mu={mu_val}, type='{plot_key}' because no finite points remain after filtering.")
                plt.close()
                continue

            grouped = plot_df.groupby(['instance_type', 'CPU'], sort=False)

            grouped_items = sorted(grouped, key=lambda item: _legend_sort_key(item[0]))

            lambda_values = sorted(plot_df['lambda'].unique())
            if len(lambda_values) >= 2:
                min_gap = min(b - a for a, b in zip(lambda_values[:-1], lambda_values[1:]))
            else:
                min_gap = max(lambda_values[0], 1.0) if lambda_values else 1.0
            # Keep jitter small: only for visualization when lines overlap exactly.
            jitter_step = min_gap * 0.015
            jitter_center = (len(unique_cpus) - 1) / 2.0

            lines_plotted = 0
            for (instance_type, cpu_val), group_data in grouped_items:
                group_data_cleaned = group_data.sort_values(by='lambda')

                if not group_data_cleaned.empty:
                    plot_color = color_map[(instance_type, cpu_val)]
                    plot_linestyle = linestyle_map.get(instance_type, '-')
                    plot_marker = marker_map.get(instance_type, '.')
                    cpu_idx = cpu_index_map.get(cpu_val, 0)
                    x_offset = (cpu_idx - jitter_center) * jitter_step
                    x_plot = group_data_cleaned['lambda'] + x_offset

                    ax.plot(x_plot, group_data_cleaned[y_col_name],
                             marker=plot_marker, linestyle=plot_linestyle, color=plot_color,
                             label=f"{instance_type}, CPU={int(cpu_val) if float(cpu_val).is_integer() else cpu_val}")
                    lines_plotted += 1

            if lines_plotted == 0:
                print(f"No valid data series to plot for mu={mu_val}, type='{plot_key}'.")
                plt.close()
                continue

            ax.set_xscale('linear')
            ax.set_xlabel("lambda")
            x_values = sorted(plot_df['lambda'].unique())
            if x_values:
                ax.set_xticks(x_values)
                if len(x_values) > 1:
                    span = x_values[-1] - x_values[0]
                    margin = span * 0.05
                    ax.set_xlim(x_values[0] - margin, x_values[-1] + margin)

            ax.set_ylabel(y_axis_label)

            # Use linear Y scale and determine readable limits/ticks from data range.
            y_min = float(plot_df[y_col_name].min())
            y_max = float(plot_df[y_col_name].max())
            if y_max <= y_min:
                base = abs(y_max) if y_max != 0 else 1.0
                y_lower = y_min - base * 0.1
                y_upper = y_max + base * 0.1
            else:
                span = y_max - y_min
                y_lower = y_min - span * 0.08
                y_upper = y_max + span * 0.12

            # Keep non-negative lower bound for these metrics.
            y_lower = max(0.0, y_lower)
            if y_upper <= y_lower:
                y_upper = y_lower + max(abs(y_lower) * 0.1, 1e-12)

            ax.set_yscale('linear')
            ax.set_ylim(y_lower, y_upper)
            ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
            ax.ticklabel_format(axis='y', style='sci', scilimits=(-3, 3), useMathText=True)

            plt.grid(True, which="both", ls="--", alpha=0.7)
            plt.legend(
                title="Series (Instance Type, λ)",
                bbox_to_anchor=(1.03, 1),
                loc='upper left',
                borderaxespad=0.,
                handlelength=LEGEND_HANDLE_LENGTH,
            )
            plt.subplots_adjust(right=0.75)

            mu_val_str = str(mu_val).replace('.', '_')
            output_filename = f"mu{mu_val_str}_{plot_key}.pdf"
            try:
                plt.savefig(output_filename, format="pdf", bbox_inches='tight')
                print(f"Saved graph: {output_filename}")
            except Exception as e:
                print(f"Error saving graph {output_filename}: {e}")

            plt.close()

        # 7. Trade-off plots (X: ave_total_50, Y: cost or energy)
        if TRADEOFF_USE_TOTAL_METRICS and 'total_cost_50' in df_mu_filtered.columns and 'total_energy_wh_50' in df_mu_filtered.columns:
            tradeoff_configs = [
                {
                    'key': 'tradeoff_total_cost_vs_total_time',
                    'x_col': 'ave_total_50',
                    'y_col': 'total_cost_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Total Cost [USD]',
                },
                {
                    'key': 'tradeoff_total_energy_vs_total_time',
                    'x_col': 'ave_total_50',
                    'y_col': 'total_energy_wh_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Total Energy [Wh]',
                },
            ]
        else:
            if TRADEOFF_USE_TOTAL_METRICS:
                print(
                    "Total trade-off columns not found (total_cost_50 / total_energy_wh_50). "
                    "Falling back to per-request metrics."
                )
            tradeoff_configs = [
                {
                    'key': 'tradeoff_cost_vs_total',
                    'x_col': 'ave_total_50',
                    'y_col': 'cost_per_request_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Cost per Request [USD/req]',
                },
                {
                    'key': 'tradeoff_energy_vs_total',
                    'x_col': 'ave_total_50',
                    'y_col': 'energy_per_request_wh_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Energy per Request [Wh/req]',
                },
            ]

        if TRADEOFF_ADD_PER_TIME_METRICS:
            tradeoff_configs.extend([
                {
                    'key': 'tradeoff_cost_per_time_vs_total_time',
                    'x_col': 'ave_total_50',
                    'y_col': 'cost_per_time_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Cost per Time [USD/s]',
                },
                {
                    'key': 'tradeoff_energy_per_time_vs_total_time',
                    'x_col': 'ave_total_50',
                    'y_col': 'energy_per_time_wh_per_sec_50',
                    'x_label': 'ave. of Total time [s]',
                    'y_label': 'Energy per Time [Wh/s]',
                },
            ])

        for tradeoff_cfg in tradeoff_configs:
            x_col = tradeoff_cfg['x_col']
            y_col = tradeoff_cfg['y_col']

            trade_df = df_mu_filtered[['lambda', 'instance_type', 'CPU', x_col, y_col]].copy()
            trade_df = trade_df.dropna(subset=['lambda', 'instance_type', 'CPU', x_col, y_col])
            trade_df = trade_df[(trade_df['lambda'] > 0) & (trade_df[x_col] >= 0) & (trade_df[y_col] >= 0)]

            if trade_df.empty:
                print(
                    f"Skipping mu={mu_val}, type='{tradeoff_cfg['key']}' because no valid points are available."
                )
                continue

            if TRADEOFF_AXIS_MODE == "linear":
                axis_variants = ["linear"]
            elif TRADEOFF_AXIS_MODE == "log":
                axis_variants = ["log"]
            else:
                axis_variants = ["linear", "log"]

            for axis_mode in axis_variants:
                variant_df = trade_df.copy()
                if axis_mode == "log":
                    variant_df = variant_df[variant_df[y_col] > 0]
                    if variant_df.empty:
                        print(
                            f"Skipping mu={mu_val}, type='{tradeoff_cfg['key']}', axis='{axis_mode}' because positive Y points are unavailable."
                        )
                        continue

                plt.figure(figsize=(12, 7))
                ax = plt.gca()

                lines_plotted = _plot_tradeoff_series(
                    ax,
                    variant_df,
                    x_col,
                    y_col,
                    axis_mode,
                    color_map,
                    linestyle_map,
                    marker_map,
                    include_labels=True,
                    annotate_lambda_endpoints=True,
                )

                if lines_plotted == 0:
                    print(
                        f"No valid trade-off series to plot for mu={mu_val}, type='{tradeoff_cfg['key']}', axis='{axis_mode}'."
                    )
                    plt.close()
                    continue

                print(f"mu={mu_val}, {tradeoff_cfg['key']}, axis={axis_mode}: plotted series = {lines_plotted}")

                x_min = float(variant_df[x_col].min())
                x_max = float(variant_df[x_col].max())
                y_min = float(variant_df[y_col].min())
                y_max = float(variant_df[y_col].max())

                x_span = x_max - x_min
                y_span = y_max - y_min

                x_pad = x_span * 0.08 if x_span > 0 else max(abs(x_max) * 0.1, 1e-12)
                y_pad = y_span * 0.12 if y_span > 0 else max(abs(y_max) * 0.1, 1e-12)

                ax.set_xlabel(tradeoff_cfg['x_label'])
                ax.set_ylabel(tradeoff_cfg['y_label'])

                if axis_mode == "log":
                    ax.set_xscale('linear')
                    ax.set_yscale('log', base=10)

                    # Y-log axis must keep strictly positive Y bounds.
                    x_lower = max(0.0, x_min - x_pad)
                    x_upper = x_max + x_pad
                    y_lower = y_min * 0.85
                    y_upper = y_max * 1.18

                    if x_upper <= x_lower:
                        x_lower = max(0.0, x_min * 0.8)
                        x_upper = x_min * 1.25 if x_min > 0 else 1.0
                    if y_upper <= y_lower:
                        y_lower = max(y_min * 0.8, 1e-15)
                        y_upper = y_min * 1.25

                    y_lower = max(y_lower, 1e-15)

                    ax.set_xlim(x_lower, x_upper)
                    ax.set_ylim(y_lower, y_upper)

                    ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                    ax.yaxis.set_major_locator(mticker.LogLocator(base=10.0, subs=(1.0,), numticks=12))
                    ax.yaxis.set_major_formatter(mticker.LogFormatterMathtext(base=10.0))
                    ax.xaxis.set_minor_locator(mticker.NullLocator())
                    ax.yaxis.set_minor_locator(mticker.LogLocator(base=10.0, subs=(2, 3, 4, 5, 6, 7, 8, 9), numticks=100))
                else:
                    ax.set_xscale('linear')
                    ax.set_yscale('linear')
                    ax.set_xlim(max(0.0, x_min - x_pad), x_max + x_pad)
                    ax.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)
                    ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                    ax.ticklabel_format(axis='both', style='sci', scilimits=(-3, 3), useMathText=True)

                endpoint_handles = _endpoint_legend_handles()

                handles, labels = ax.get_legend_handles_labels()
                handles.extend(endpoint_handles)
                labels.extend(['min lambda in series', 'max lambda in series'])

                plt.grid(True, which="both", ls="--", alpha=0.7)
                plt.legend(
                    handles,
                    labels,
                    title="Series / Endpoints",
                    bbox_to_anchor=(1.03, 1),
                    loc='upper left',
                    borderaxespad=0.,
                    handlelength=LEGEND_HANDLE_LENGTH,
                )
                plt.subplots_adjust(right=0.75)

                mu_val_str = str(mu_val).replace('.', '_')
                output_filename = f"mu{mu_val_str}_{tradeoff_cfg['key']}_{axis_mode}.pdf"
                try:
                    plt.savefig(output_filename, format="pdf", bbox_inches='tight')
                    print(f"Saved graph: {output_filename}")
                except Exception as e:
                    print(f"Error saving graph {output_filename}: {e}")

                plt.close()

                focus_ranges = _compute_x_focus_ranges(variant_df[x_col])

                if TRADEOFF_ADD_LEFT_INSET and focus_ranges is not None:
                    plt.figure(figsize=(12, 7))
                    ax_main = plt.gca()

                    inset_lines = _plot_tradeoff_series(
                        ax_main,
                        variant_df,
                        x_col,
                        y_col,
                        axis_mode,
                        color_map,
                        linestyle_map,
                        marker_map,
                        include_labels=True,
                        annotate_lambda_endpoints=False,
                    )
                    if inset_lines > 0:
                        ax_main.set_xlabel(tradeoff_cfg['x_label'])
                        ax_main.set_ylabel(tradeoff_cfg['y_label'])

                        if axis_mode == "log":
                            ax_main.set_xscale('linear')
                            ax_main.set_yscale('log', base=10)
                            ax_main.set_xlim(x_lower, x_upper)
                            ax_main.set_ylim(y_lower, y_upper)
                            ax_main.xaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                            ax_main.yaxis.set_major_locator(mticker.LogLocator(base=10.0, subs=(1.0,), numticks=12))
                            ax_main.yaxis.set_major_formatter(mticker.LogFormatterMathtext(base=10.0))
                            ax_main.xaxis.set_minor_locator(mticker.NullLocator())
                            ax_main.yaxis.set_minor_locator(mticker.LogLocator(base=10.0, subs=(2, 3, 4, 5, 6, 7, 8, 9), numticks=100))
                        else:
                            ax_main.set_xscale('linear')
                            ax_main.set_yscale('linear')
                            ax_main.set_xlim(max(0.0, x_min - x_pad), x_max + x_pad)
                            ax_main.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)
                            ax_main.xaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                            ax_main.yaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                            ax_main.ticklabel_format(axis='both', style='sci', scilimits=(-3, 3), useMathText=True)

                        ax_inset = ax_main.inset_axes([0.55, 0.56, 0.4, 0.4])
                        _plot_tradeoff_series(
                            ax_inset,
                            variant_df,
                            x_col,
                            y_col,
                            axis_mode,
                            color_map,
                            linestyle_map,
                            marker_map,
                            include_labels=False,
                            annotate_lambda_endpoints=False,
                        )

                        ax_inset.set_xlim(focus_ranges['left_xlim'][0], focus_ranges['left_xlim'][1])
                        if axis_mode == "log":
                            ax_inset.set_xscale('linear')
                            ax_inset.set_yscale('log', base=10)
                            ax_inset.set_ylim(y_lower, y_upper)
                            ax_inset.yaxis.set_major_locator(mticker.LogLocator(base=10.0, subs=(1.0,), numticks=6))
                            ax_inset.yaxis.set_major_formatter(mticker.LogFormatterMathtext(base=10.0))
                            ax_inset.yaxis.set_minor_locator(mticker.LogLocator(base=10.0, subs=(2, 5), numticks=20))
                        else:
                            ax_inset.set_xscale('linear')
                            ax_inset.set_yscale('linear')
                            ax_inset.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)
                            ax_inset.ticklabel_format(axis='both', style='sci', scilimits=(-3, 3), useMathText=True)

                        ax_inset.grid(True, which="both", ls="--", alpha=0.5)

                        handles, labels = ax_main.get_legend_handles_labels()
                        handles.extend(_endpoint_legend_handles())
                        labels.extend(['min lambda in series', 'max lambda in series'])

                        plt.grid(True, which="both", ls="--", alpha=0.7)
                        plt.legend(
                            handles,
                            labels,
                            title="Series / Endpoints",
                            bbox_to_anchor=(1.03, 1),
                            loc='upper left',
                            borderaxespad=0.,
                            handlelength=LEGEND_HANDLE_LENGTH,
                        )
                        plt.subplots_adjust(right=0.75)
                        plt.title(f"Left-zoom inset (max gap ratio={focus_ranges['split_ratio']:.3g})")

                        inset_output_filename = f"mu{mu_val_str}_{tradeoff_cfg['key']}_{axis_mode}_inset.pdf"
                        try:
                            plt.savefig(inset_output_filename, format="pdf", bbox_inches='tight')
                            print(f"Saved graph: {inset_output_filename}")
                        except Exception as e:
                            print(f"Error saving graph {inset_output_filename}: {e}")
                    plt.close()

                if TRADEOFF_ADD_BROKEN_X and focus_ranges is not None:
                    fig, (ax_left, ax_right) = plt.subplots(
                        1,
                        2,
                        sharey=True,
                        figsize=(13, 7),
                        gridspec_kw={'width_ratios': [1, 1], 'wspace': 0.06},
                    )

                    left_lines = _plot_tradeoff_series(
                        ax_left,
                        variant_df,
                        x_col,
                        y_col,
                        axis_mode,
                        color_map,
                        linestyle_map,
                        marker_map,
                        include_labels=True,
                        annotate_lambda_endpoints=False,
                    )
                    _plot_tradeoff_series(
                        ax_right,
                        variant_df,
                        x_col,
                        y_col,
                        axis_mode,
                        color_map,
                        linestyle_map,
                        marker_map,
                        include_labels=False,
                        annotate_lambda_endpoints=False,
                    )

                    if left_lines > 0:
                        ax_left.set_xlim(focus_ranges['left_xlim'][0], focus_ranges['left_xlim'][1])
                        ax_right.set_xlim(focus_ranges['right_xlim'][0], focus_ranges['right_xlim'][1])

                        if axis_mode == "log":
                            for broken_ax in (ax_left, ax_right):
                                broken_ax.set_xscale('linear')
                                broken_ax.set_yscale('log', base=10)
                                broken_ax.set_ylim(y_lower, y_upper)
                                broken_ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=6, min_n_ticks=3))
                                broken_ax.yaxis.set_major_locator(mticker.LogLocator(base=10.0, subs=(1.0,), numticks=12))
                                broken_ax.yaxis.set_major_formatter(mticker.LogFormatterMathtext(base=10.0))
                                broken_ax.xaxis.set_minor_locator(mticker.NullLocator())
                                broken_ax.yaxis.set_minor_locator(mticker.LogLocator(base=10.0, subs=(2, 5), numticks=30))
                        else:
                            for broken_ax in (ax_left, ax_right):
                                broken_ax.set_xscale('linear')
                                broken_ax.set_yscale('linear')
                                broken_ax.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)
                                broken_ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=6, min_n_ticks=3))
                                broken_ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=8, min_n_ticks=4))
                                broken_ax.ticklabel_format(axis='both', style='sci', scilimits=(-3, 3), useMathText=True)

                        ax_left.grid(True, which="both", ls="--", alpha=0.7)
                        ax_right.grid(True, which="both", ls="--", alpha=0.7)

                        ax_left.spines['right'].set_visible(False)
                        ax_right.spines['left'].set_visible(False)
                        ax_right.tick_params(labelleft=False)

                        d = 0.012
                        kwargs = dict(transform=ax_left.transAxes, color='k', clip_on=False, linewidth=1.0)
                        ax_left.plot((1 - d, 1 + d), (-d, +d), **kwargs)
                        ax_left.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)
                        kwargs.update(transform=ax_right.transAxes)
                        ax_right.plot((-d, +d), (-d, +d), **kwargs)
                        ax_right.plot((-d, +d), (1 - d, 1 + d), **kwargs)

                        handles, labels = ax_left.get_legend_handles_labels()
                        handles.extend(_endpoint_legend_handles())
                        labels.extend(['min lambda in series', 'max lambda in series'])
                        ax_right.legend(
                            handles,
                            labels,
                            title="Series / Endpoints",
                            bbox_to_anchor=(1.03, 1),
                            loc='upper left',
                            borderaxespad=0.,
                            handlelength=LEGEND_HANDLE_LENGTH,
                        )

                        ax_left.set_ylabel(tradeoff_cfg['y_label'])
                        fig.supxlabel(tradeoff_cfg['x_label'])
                        fig.suptitle(f"Broken x-axis trade-off (max gap ratio={focus_ranges['split_ratio']:.3g})")
                        fig.subplots_adjust(right=0.76)

                        broken_output_filename = f"mu{mu_val_str}_{tradeoff_cfg['key']}_{axis_mode}_brokenx.pdf"
                        try:
                            fig.savefig(broken_output_filename, format="pdf", bbox_inches='tight')
                            print(f"Saved graph: {broken_output_filename}")
                        except Exception as e:
                            print(f"Error saving graph {broken_output_filename}: {e}")

                    plt.close(fig)

def main():
    parser = argparse.ArgumentParser(
        description="Generates graphs from a processed CSV file. "\
                    "The CSV file is expected to be the output of the previous data processing script."
    )
    parser.add_argument(
        'csv_file',
        help="Path to the input CSV file."
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csv_file):
        print(f"Error: The file '{args.csv_file}' does not exist.")
        return

    plot_graphs(args.csv_file)

if __name__ == '__main__':
    main()