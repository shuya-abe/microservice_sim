import argparse
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd


PERCENTAGE_SUFFIXES = ["50", "40", "30", "20", "10"]
PERCENTAGE_DECIMALS = [0.5, 0.4, 0.3, 0.2, 0.1]


def companion_result_path(packet_csv_path):
    """Map *_packet.csv -> *_result.csv."""
    if packet_csv_path.endswith("_packet.csv"):
        return packet_csv_path[: -len("_packet.csv")] + "_result.csv"
    return packet_csv_path.rsplit(".", 1)[0] + "_result.csv"


def read_steady_window_from_result(packet_csv_path):
    """
    If the simulator wrote steady_start/steady_end on the companion result CSV,
    return (start, end, result_row_dict). Otherwise (None, None, None).
    """
    result_path = companion_result_path(packet_csv_path)
    if not os.path.exists(result_path):
        return None, None, None
    try:
        rdf = pd.read_csv(result_path)
    except Exception as e:
        print(f"警告: result CSV 読み込み失敗: {result_path} - {e}")
        return None, None, None
    if rdf.empty:
        return None, None, None
    row = rdf.iloc[0].to_dict()
    if "steady_start" not in rdf.columns or "steady_end" not in rdf.columns:
        return None, None, None
    start = pd.to_numeric(row.get("steady_start"), errors="coerce")
    end = pd.to_numeric(row.get("steady_end"), errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return None, None, None
    enabled = row.get("steady_enabled", True)
    if isinstance(enabled, str) and enabled.strip().lower() in ("false", "0", "no"):
        return None, None, None
    if enabled is False or enabled == 0:
        return None, None, None
    return float(start), float(end), row


def round_to_significant_figures(number, sig_figs):
    """指定された数値を有効数字sig_figs桁に丸めます。NaNや0はそのまま返します。"""
    if pd.isna(number) or number == 0:
        return number
    if not isinstance(sig_figs, int) or sig_figs <= 0:
        raise ValueError("有効数字の桁数は正の整数である必要があります。")
    try:
        return float(f"{number:.{sig_figs}g}")
    except (ValueError, TypeError):
        return number


def parse_filename(filename_basename):
    """ファイル名からメタデータを抽出します。接頭辞は任意（experiment_id等）です。"""
    # Prefix is intentionally flexible: experiment IDs like "abc" or timestamps are both valid.
    pattern = re.compile(
        r"(.+?)_"                    # experiment_id / prefix
        r"(\d+)srv_"                # servers
        r"(\d+)CPU_"                # CPU
        r".*?lambda([\d.eE+-]+)_"   # lambda
        r"mu([\d.eE+-]+)_"          # mu
        r"(container|serverless_warm_wait|serverless)_"  # platform
        r"(\d+)_packet\.csv"       # run index
    )
    match = pattern.search(filename_basename)
    if match:
        return {
            "datetime": match.group(1),
            "servers": int(match.group(2)),
            "CPU": int(match.group(3)),
            "lambda": float(match.group(4)),
            "mu": float(match.group(5)),
            "platform": match.group(6),
            "run_index": int(match.group(7)),
        }

    fallback = re.compile(
        r"(.+?)_"
        r"(\d+)srv_"
        r"(\d+)CPU_"
        r".*?lambda([\d.eE+-]+)_"
        r"mu([\d.eE+-]+)_"
        r".*_packet\.csv"
    )
    match_fallback = fallback.search(filename_basename)
    if match_fallback:
        return {
            "datetime": match_fallback.group(1),
            "servers": int(match_fallback.group(2)),
            "CPU": int(match_fallback.group(3)),
            "lambda": float(match_fallback.group(4)),
            "mu": float(match_fallback.group(5)),
            "platform": "unknown",
            "run_index": np.nan,
        }

    print(f"警告: ファイル名 '{filename_basename}' が期待パターンに一致しません。")
    return {
        "datetime": "N/A",
        "servers": np.nan,
        "CPU": np.nan,
        "lambda": np.nan,
        "mu": np.nan,
        "platform": "unknown",
        "run_index": np.nan,
    }


def determine_instance_type(df):
    """processedBy列から instance_type を判定します。"""
    determined_instance_type = "other"
    processed_col = None
    if "processedBy" in df.columns:
        processed_col = "processedBy"
    elif "processed_by" in df.columns:
        processed_col = "processed_by"

    if processed_col is None:
        return determined_instance_type

    pb_series_cleaned = df[processed_col].dropna().astype(str)
    if pb_series_cleaned.empty:
        return determined_instance_type

    has_warm_wait = pb_series_cleaned.str.startswith("serverless_warm_wait").any()
    has_plain_serverless = pb_series_cleaned.str.match(r"^serverless\d+$").any()
    has_container = pb_series_cleaned.str.startswith("container").any()

    type_flags = sum([has_warm_wait, has_plain_serverless, has_container])
    if type_flags > 1:
        return "hybrid"
    if has_warm_wait:
        return "serverless_warm_wait" if pb_series_cleaned.str.startswith("serverless_warm_wait").all() else "other"
    if has_plain_serverless:
        return "serverless" if pb_series_cleaned.str.match(r"^serverless\d+$").all() else "other"
    if has_container:
        return "container" if pb_series_cleaned.str.startswith("container").all() else "other"
    return determined_instance_type


def read_analysis_csv_for_packet(packet_csv_path):
    """対応する *_analysis.csv を読み込みます。存在しない場合は None を返します。"""
    analysis_csv_path = packet_csv_path.replace("_packet.csv", "_analysis.csv")
    if analysis_csv_path == packet_csv_path:
        analysis_csv_path = packet_csv_path.rsplit(".", 1)[0] + "_analysis.csv"

    if not os.path.exists(analysis_csv_path):
        print(f"警告: 対応する analysis CSV が見つかりません: {analysis_csv_path}")
        return None

    try:
        analysis_df = pd.read_csv(analysis_csv_path)
    except Exception as e:
        print(f"警告: analysis CSV 読み込み失敗: {analysis_csv_path} - {e}")
        return None

    if "time" in analysis_df.columns:
        analysis_df["time"] = pd.to_numeric(analysis_df["time"], errors="coerce")

    for col in ["cost_a_step", "cost_b_step", "total_power_wh", "total_power_w", "num_instances"]:
        if col in analysis_df.columns:
            analysis_df[col] = pd.to_numeric(analysis_df[col], errors="coerce")

    return analysis_df


def read_num_instance_csv_for_packet(packet_csv_path):
    """対応する *_num_instance.csv を読み込みます。存在しない場合は None を返します。"""
    num_instance_path = packet_csv_path.replace("_packet.csv", "_num_instance.csv")
    if num_instance_path == packet_csv_path:
        num_instance_path = packet_csv_path.rsplit(".", 1)[0] + "_num_instance.csv"

    if not os.path.exists(num_instance_path):
        return None

    try:
        ni_df = pd.read_csv(num_instance_path)
    except Exception as e:
        print(f"警告: num_instance CSV 読み込み失敗: {num_instance_path} - {e}")
        return None

    time_col = "sim_time" if "sim_time" in ni_df.columns else ("time" if "time" in ni_df.columns else None)
    count_col = (
        "num_hot_instances" if "num_hot_instances" in ni_df.columns
        else ("num_instances" if "num_instances" in ni_df.columns else None)
    )
    if time_col is None or count_col is None:
        return None

    out = pd.DataFrame({
        "time": pd.to_numeric(ni_df[time_col], errors="coerce"),
        "num_instances": pd.to_numeric(ni_df[count_col], errors="coerce"),
    }).dropna()
    return out.sort_values("time").reset_index(drop=True)


def time_weighted_average_instances(change_df, window_start, window_end):
    """
    変化点ログ（time, num_instances）から、[window_start, window_end] の時間加重平均台数を計算します。
    num_instances[i] は time[i] 以降、次の変化点まで一定とみなします。
    """
    if (
        change_df is None or change_df.empty
        or pd.isna(window_start) or pd.isna(window_end)
        or float(window_end) <= float(window_start)
    ):
        return np.nan

    times = change_df["time"].to_numpy(dtype=float)
    values = change_df["num_instances"].to_numpy(dtype=float)
    w0 = float(window_start)
    w1 = float(window_end)

    # value in effect at w0: last change at or before w0, else first known value
    idx = int(np.searchsorted(times, w0, side="right") - 1)
    if idx < 0:
        if times[0] >= w1:
            return np.nan
        current_value = float(values[0])
        cursor = max(w0, float(times[0]))
        idx = 0
    else:
        current_value = float(values[idx])
        cursor = w0

    integral = 0.0
    while cursor < w1:
        next_change = float(times[idx + 1]) if (idx + 1) < len(times) else w1
        segment_end = min(w1, next_change)
        if segment_end > cursor:
            integral += current_value * (segment_end - cursor)
            cursor = segment_end
        if cursor >= w1:
            break
        idx += 1
        if idx >= len(values):
            break
        current_value = float(values[idx])

    elapsed = w1 - w0
    if elapsed <= 0:
        return np.nan
    return integral / elapsed


def compute_window_cost_power_metrics(analysis_df, window_start, window_end, num_reqs, num_instance_df=None):
    """
    window_start から window_end の区間で、コスト・電力量・平均インスタンス数を計算します。
    区間以前の課金/電力消費は無かったものとして扱います（区間内積算のみ）。
    """
    result = {
        "window_elapsed_time": np.nan,
        "window_total_cost": np.nan,
        "window_total_energy_wh": np.nan,
        "window_cost_per_time": np.nan,
        "window_energy_per_time_wh_per_sec": np.nan,
        "window_average_power_w": np.nan,
        "window_cost_per_request": np.nan,
        "window_energy_per_request_wh": np.nan,
        "window_avg_cpu_utilization": np.nan,
        "window_ave_instances": np.nan,
    }

    if pd.isna(window_start) or pd.isna(window_end):
        return result

    elapsed = float(window_end - window_start)
    if elapsed <= 0:
        return result

    result["window_elapsed_time"] = elapsed

    # Prefer dedicated num_instance change log; fall back to analysis num_instances.
    if num_instance_df is not None and not num_instance_df.empty:
        result["window_ave_instances"] = time_weighted_average_instances(
            num_instance_df, window_start, window_end
        )
    elif analysis_df is not None and "time" in analysis_df.columns and "num_instances" in analysis_df.columns:
        change_df = analysis_df[["time", "num_instances"]].dropna().sort_values("time")
        result["window_ave_instances"] = time_weighted_average_instances(
            change_df, window_start, window_end
        )

    if analysis_df is None or "time" not in analysis_df.columns:
        return result

    win = analysis_df[(analysis_df["time"] >= window_start) & (analysis_df["time"] <= window_end)].copy()
    if win.empty:
        return result

    if "cost_a_step" in win.columns and "cost_b_step" in win.columns:
        total_cost = (win["cost_a_step"].fillna(0) + win["cost_b_step"].fillna(0)).sum()
    else:
        total_cost = np.nan

    if "total_power_wh" in win.columns:
        total_energy_wh = win["total_power_wh"].fillna(0).sum()
    elif "total_power_w" in win.columns and len(win) >= 2:
        dt = win["time"].sort_values().diff().median()
        if pd.notna(dt) and dt > 0:
            total_energy_wh = (win["total_power_w"].fillna(0) * dt / 3600.0).sum()
        else:
            total_energy_wh = np.nan
    else:
        total_energy_wh = np.nan

    result["window_total_cost"] = total_cost
    result["window_total_energy_wh"] = total_energy_wh

    if "num_processing_cpus" in win.columns and "num_total_attached_cpus" in win.columns:
        cpu_total = pd.to_numeric(win["num_total_attached_cpus"], errors="coerce")
        cpu_proc = pd.to_numeric(win["num_processing_cpus"], errors="coerce")
        valid_mask = cpu_total > 0
        if valid_mask.any():
            util_series = cpu_proc[valid_mask] / cpu_total[valid_mask]
            result["window_avg_cpu_utilization"] = float(util_series.mean())

    if pd.notna(total_cost):
        result["window_cost_per_time"] = total_cost / elapsed
        if num_reqs > 0:
            result["window_cost_per_request"] = total_cost / num_reqs

    if pd.notna(total_energy_wh):
        result["window_energy_per_time_wh_per_sec"] = total_energy_wh / elapsed
        result["window_average_power_w"] = total_energy_wh / (elapsed / 3600.0)
        if num_reqs > 0:
            result["window_energy_per_request_wh"] = total_energy_wh / num_reqs

    return result


def process_csv_file(filepath):
    """単一CSVを処理し、各抽出割合の統計と区間コスト/電力を返します。"""
    print(f"\n--- ファイルを処理中: {filepath} ---")
    try:
        df_initial_load = pd.read_csv(filepath)
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {filepath}")
        return None
    except pd.errors.EmptyDataError:
        print(f"エラー: ファイルが空です: {filepath}")
        return None
    except Exception as e:
        print(f"エラー: CSVファイル {filepath} の読み込み中にエラー: {e}")
        return None

    required_columns = [
        "id", "workload", "start", "end",
        "time_lifetime", "time_wait", "time_service"
    ]
    has_processed = ("processedBy" in df_initial_load.columns) or ("processed_by" in df_initial_load.columns)
    if not has_processed:
        missing_cols = ["processedBy/processed_by"]
    else:
        missing_cols = []

    missing_cols.extend([col for col in required_columns if col not in df_initial_load.columns])
    if missing_cols:
        print(f"エラー: ファイル {filepath} に必要な列がありません: {', '.join(missing_cols)}")
        return None

    if df_initial_load.empty:
        print(f"ファイル {filepath} にデータ行がありません。")
        return None

    determined_instance_type = determine_instance_type(df_initial_load)

    df = df_initial_load.copy()
    numeric_cols = ["start", "end", "time_lifetime", "time_wait", "time_service"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=["start", "end"], inplace=True)
    if df.empty:
        print(f"有効な start/end データがありません: {filepath}")
        return None

    original_valid_row_count = len(df)
    max_start_time = df["start"].max()
    df_step1_filtered = df[df["end"] <= max_start_time].copy()

    if df_step1_filtered.empty:
        print(f"ステップ1フィルタ後にデータがありません: {filepath}")

    analysis_df = read_analysis_csv_for_packet(filepath)
    num_instance_df = read_num_instance_csv_for_packet(filepath)
    calculated_stats = {"instance_type": determined_instance_type}

    steady_start, steady_end, steady_row = read_steady_window_from_result(filepath)
    if steady_start is not None and steady_end is not None:
        # Simulator already decided the steady window: one set of metrics, no %-tail.
        calculated_stats["steady_mode"] = True
        win = df[(df["end"] >= steady_start) & (df["end"] <= steady_end)].copy()
        if win.empty:
            win = df[(df["start"] >= steady_start) & (df["end"] <= steady_end)].copy()
        num_extracted = len(win)
        if num_extracted > 0:
            ave_total = float(win["time_lifetime"].mean())
            ave_wait = float(win["time_wait"].mean())
            ave_service = float(win["time_service"].mean())
            window_start = float(win["start"].min())
            window_end = float(win["end"].max())
        else:
            # Fall back to simulator-reported means when packet filtering is empty.
            ave_total = pd.to_numeric(steady_row.get("ex_time_total"), errors="coerce")
            ave_wait = pd.to_numeric(steady_row.get("ex_time_wait"), errors="coerce")
            ave_service = pd.to_numeric(steady_row.get("ex_time_service"), errors="coerce")
            window_start, window_end = steady_start, steady_end
            num_extracted = int(pd.to_numeric(steady_row.get("num_reqs"), errors="coerce") or 0)

        window_metrics = compute_window_cost_power_metrics(
            analysis_df=analysis_df,
            window_start=steady_start,
            window_end=steady_end,
            num_reqs=num_extracted,
            num_instance_df=num_instance_df,
        )
        if pd.isna(window_metrics.get("window_ave_instances")) and steady_row is not None:
            window_metrics["window_ave_instances"] = pd.to_numeric(
                steady_row.get("ave_instances_steady"), errors="coerce"
            )

        steady_fields = {
            "num_reqs": num_extracted,
            "ave_total": ave_total,
            "ave_wait": ave_wait,
            "ave_service": ave_service,
            "window_start": window_start,
            "window_end": window_end,
            "elapsed_time": window_metrics["window_elapsed_time"],
            "total_cost": window_metrics["window_total_cost"],
            "total_energy_wh": window_metrics["window_total_energy_wh"],
            "cost_per_time": window_metrics["window_cost_per_time"],
            "energy_per_time_wh_per_sec": window_metrics["window_energy_per_time_wh_per_sec"],
            "average_power_w": window_metrics["window_average_power_w"],
            "cost_per_request": window_metrics["window_cost_per_request"],
            "energy_per_request_wh": window_metrics["window_energy_per_request_wh"],
            "avg_cpu_utilization": window_metrics["window_avg_cpu_utilization"],
            "ave_instances": window_metrics["window_ave_instances"],
        }
        for key, value in steady_fields.items():
            calculated_stats[key] = value
            # Compatibility alias for older graph scripts that expect *_50.
            calculated_stats[f"{key}_50"] = value

        print(f"--- {filepath} の処理終了 (steady window [{steady_start}, {steady_end}]) ---")
        return calculated_stats

    # Legacy path: trailing-percentage windows (deprecated when steady result exists).
    calculated_stats["steady_mode"] = False
    sorted_for_extract = df_step1_filtered.sort_values(by="end", ascending=False)

    for p_decimal in PERCENTAGE_DECIMALS:
        p_suffix = str(int(p_decimal * 100))
        num_to_extract = int(original_valid_row_count * p_decimal)

        if num_to_extract <= 0 or sorted_for_extract.empty:
            extracted = pd.DataFrame(columns=sorted_for_extract.columns)
        else:
            extracted = sorted_for_extract.head(num_to_extract)

        num_extracted = len(extracted)

        calculated_stats[f"num_reqs_{p_suffix}"] = num_extracted
        calculated_stats[f"ave_total_{p_suffix}"] = extracted["time_lifetime"].mean()
        calculated_stats[f"ave_wait_{p_suffix}"] = extracted["time_wait"].mean()
        calculated_stats[f"ave_service_{p_suffix}"] = extracted["time_service"].mean()

        if num_extracted > 0:
            window_start = extracted["start"].min()
            window_end = extracted["end"].max()
        else:
            window_start = np.nan
            window_end = np.nan

        calculated_stats[f"window_start_{p_suffix}"] = window_start
        calculated_stats[f"window_end_{p_suffix}"] = window_end

        window_metrics = compute_window_cost_power_metrics(
            analysis_df=analysis_df,
            window_start=window_start,
            window_end=window_end,
            num_reqs=num_extracted,
            num_instance_df=num_instance_df,
        )

        calculated_stats[f"elapsed_time_{p_suffix}"] = window_metrics["window_elapsed_time"]
        calculated_stats[f"total_cost_{p_suffix}"] = window_metrics["window_total_cost"]
        calculated_stats[f"total_energy_wh_{p_suffix}"] = window_metrics["window_total_energy_wh"]
        calculated_stats[f"cost_per_time_{p_suffix}"] = window_metrics["window_cost_per_time"]
        calculated_stats[f"energy_per_time_wh_per_sec_{p_suffix}"] = window_metrics[
            "window_energy_per_time_wh_per_sec"
        ]
        calculated_stats[f"average_power_w_{p_suffix}"] = window_metrics["window_average_power_w"]
        calculated_stats[f"cost_per_request_{p_suffix}"] = window_metrics["window_cost_per_request"]
        calculated_stats[f"energy_per_request_wh_{p_suffix}"] = window_metrics[
            "window_energy_per_request_wh"
        ]
        calculated_stats[f"avg_cpu_utilization_{p_suffix}"] = window_metrics[
            "window_avg_cpu_utilization"
        ]
        calculated_stats[f"ave_instances_{p_suffix}"] = window_metrics["window_ave_instances"]

    print(f"--- {filepath} の処理終了 ---")
    return calculated_stats


def aggregate_rows_by_config(rows, step_per_time):
    """
    同時に渡されたファイルについて、日時を無視して同一設定を平均化します。
    平均キー: (lambda, mu, servers, CPU, instance_type, step_per_time)
    """
    grouped = {}
    for row in rows:
        key = (
            row.get("lambda"),
            row.get("mu"),
            row.get("servers"),
            row.get("CPU"),
            row.get("instance_type"),
            step_per_time,
        )
        grouped.setdefault(key, []).append(row)

    aggregated_rows = []

    metric_prefixes = [
        "num_reqs", "ave_total", "ave_wait", "ave_service",
        "window_start", "window_end", "elapsed_time",
        "total_cost", "total_energy_wh",
        "cost_per_time", "energy_per_time_wh_per_sec", "average_power_w",
        "cost_per_request", "energy_per_request_wh", "avg_cpu_utilization",
        "ave_instances",
    ]

    for key, members in grouped.items():
        lamb, mu, servers, cpu, instance_type, spt = key
        datetimes = sorted({str(m.get("datetime", "N/A")) for m in members})

        agg = {
            "datetime": "|".join(datetimes),
            "lambda": lamb,
            "mu": mu,
            "servers": servers,
            "CPU": cpu,
            "instance_type": instance_type,
            "step_per_time": spt,
            "num_files_averaged": len(members),
            "steady_mode": any(bool(m.get("steady_mode")) for m in members),
        }

        for prefix in metric_prefixes:
            # Unsuffixed steady columns.
            if any(prefix in m for m in members):
                values = pd.to_numeric([m.get(prefix, np.nan) for m in members], errors="coerce")
                agg[prefix] = float(np.nanmean(values)) if not np.all(np.isnan(values)) else np.nan
            for sfx in PERCENTAGE_SUFFIXES:
                col = f"{prefix}_{sfx}"
                values = pd.to_numeric([m.get(col, np.nan) for m in members], errors="coerce")
                agg[col] = float(np.nanmean(values)) if not np.all(np.isnan(values)) else np.nan

        aggregated_rows.append(agg)

    return aggregated_rows


def main():
    parser = argparse.ArgumentParser(
        description=(
            "通信データCSVファイルを処理し、同一設定（日時違い含む）を平均化した集計CSVを生成します。\n"
            "使用例: python enhanced_process_result.py file1_packet.csv file2_packet.csv 100"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "input_args",
        nargs="+",
        metavar="ARG",
        help="処理するCSVファイルパス列と、最後に整数 step_per_time",
    )

    args = parser.parse_args()
    if len(args.input_args) < 2:
        parser.error("少なくとも1つのCSVファイルと step_per_time が必要です。")

    csv_files = args.input_args[:-1]
    try:
        step_per_time = int(args.input_args[-1])
    except ValueError:
        parser.error("最後の引数 step_per_time は整数で指定してください。")

    per_file_rows = []

    for csv_file_path in csv_files:
        filename_basename = os.path.basename(csv_file_path)
        parsed_name_info = parse_filename(filename_basename)

        processing_results = process_csv_file(csv_file_path)
        if processing_results is None:
            print(f"情報: {filename_basename} は処理エラーのためスキップします。")
            continue

        instance_type = processing_results.get("instance_type", "N/A")
        platform = parsed_name_info.get("platform")
        if platform in ("serverless_warm_wait", "container", "serverless"):
            instance_type = platform

        row = {
            "datetime": parsed_name_info["datetime"],
            "lambda": parsed_name_info["lambda"],
            "mu": parsed_name_info["mu"],
            "servers": parsed_name_info["servers"],
            "CPU": parsed_name_info["CPU"],
            "instance_type": instance_type,
            "step_per_time": step_per_time,
            "steady_mode": bool(processing_results.get("steady_mode", False)),
        }

        # Preferred unsuffixed steady metrics (when present).
        for prefix in [
            "num_reqs", "ave_total", "ave_wait", "ave_service",
            "window_start", "window_end", "elapsed_time",
            "total_cost", "total_energy_wh",
            "cost_per_time", "energy_per_time_wh_per_sec", "average_power_w",
            "cost_per_request", "energy_per_request_wh", "ave_instances",
        ]:
            if prefix in processing_results:
                val = processing_results.get(prefix, np.nan)
                if prefix.startswith("ave_"):
                    row[prefix] = round_to_significant_figures(val, 4)
                else:
                    row[prefix] = val

        for p_sfx in PERCENTAGE_SUFFIXES:
            row[f"num_reqs_{p_sfx}"] = processing_results.get(f"num_reqs_{p_sfx}", np.nan)
            row[f"ave_total_{p_sfx}"] = round_to_significant_figures(
                processing_results.get(f"ave_total_{p_sfx}", np.nan), 4
            )
            row[f"ave_wait_{p_sfx}"] = round_to_significant_figures(
                processing_results.get(f"ave_wait_{p_sfx}", np.nan), 4
            )
            row[f"ave_service_{p_sfx}"] = round_to_significant_figures(
                processing_results.get(f"ave_service_{p_sfx}", np.nan), 4
            )

            # 追加の区間メトリクス
            for extra_prefix in [
                "window_start", "window_end", "elapsed_time",
                "total_cost", "total_energy_wh",
                "cost_per_time", "energy_per_time_wh_per_sec", "average_power_w",
                "cost_per_request", "energy_per_request_wh", "ave_instances",
            ]:
                row[f"{extra_prefix}_{p_sfx}"] = processing_results.get(
                    f"{extra_prefix}_{p_sfx}", np.nan
                )

        per_file_rows.append(row)

    if not per_file_rows:
        print("\n集計CSVを生成するための処理済みデータがありません。")
        return

    aggregated_rows = aggregate_rows_by_config(per_file_rows, step_per_time)
    output_df = pd.DataFrame(aggregated_rows)

    # 列順を整理
    base_columns = [
        "datetime", "lambda", "mu", "servers", "CPU", "instance_type",
        "step_per_time", "num_files_averaged", "steady_mode",
    ]

    ordered_metric_columns = []
    for prefix in [
        "num_reqs", "ave_total", "ave_wait", "ave_service",
        "window_start", "window_end", "elapsed_time",
        "total_cost", "total_energy_wh",
        "cost_per_time", "energy_per_time_wh_per_sec", "average_power_w",
        "cost_per_request", "energy_per_request_wh", "ave_instances",
    ]:
        ordered_metric_columns.append(prefix)
        for sfx in PERCENTAGE_SUFFIXES:
            ordered_metric_columns.append(f"{prefix}_{sfx}")

    output_columns = [c for c in base_columns + ordered_metric_columns if c in output_df.columns]
    output_df = output_df[output_columns]

    # 丸め（可読性向上）
    for col in output_df.columns:
        if col.startswith("num_reqs_"):
            output_df[col] = output_df[col].round(0)
        elif col in ["servers", "CPU", "step_per_time", "num_files_averaged"]:
            continue
        elif col not in ["datetime", "instance_type"]:
            output_df[col] = output_df[col].apply(lambda x: round_to_significant_figures(x, 6))

    output_timestamp = datetime.now().strftime("%Y%m%d%H%M")
    output_filename = f"rev_result_{output_timestamp}.csv"

    try:
        output_df.to_csv(output_filename, index=False, na_rep="N/A")
        print(f"\n集計結果を保存しました: {output_filename}")
        print("同時入力ファイル内で、日時を無視した同一設定平均を適用しています。")
    except Exception as e:
        print(f"エラー: 集計CSV {output_filename} の保存中にエラー: {e}")


if __name__ == "__main__":
    main()
