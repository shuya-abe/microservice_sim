import argparse
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd


PERCENTAGE_SUFFIXES = ["50", "40", "30", "20", "10"]
PERCENTAGE_DECIMALS = [0.5, 0.4, 0.3, 0.2, 0.1]


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
        r"([a-zA-Z]+)_"              # platform/container/serverless
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

    has_serverless = pb_series_cleaned.str.startswith("serverless").any()
    has_container = pb_series_cleaned.str.startswith("container").any()

    if has_serverless and has_container:
        return "hybrid"
    if has_serverless:
        return "serverless" if pb_series_cleaned.str.startswith("serverless").all() else "other"
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

    for col in ["cost_a_step", "cost_b_step", "total_power_wh", "total_power_w"]:
        if col in analysis_df.columns:
            analysis_df[col] = pd.to_numeric(analysis_df[col], errors="coerce")

    return analysis_df


def compute_window_cost_power_metrics(analysis_df, window_start, window_end, num_reqs):
    """
    window_start から window_end の区間で、コスト・電力量指標を計算します。
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
    }

    if pd.isna(window_start) or pd.isna(window_end):
        return result

    elapsed = float(window_end - window_start)
    if elapsed <= 0:
        return result

    result["window_elapsed_time"] = elapsed

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
    sorted_for_extract = df_step1_filtered.sort_values(by="end", ascending=False)

    calculated_stats = {"instance_type": determined_instance_type}

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
        }

        for prefix in metric_prefixes:
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

        row = {
            "datetime": parsed_name_info["datetime"],
            "lambda": parsed_name_info["lambda"],
            "mu": parsed_name_info["mu"],
            "servers": parsed_name_info["servers"],
            "CPU": parsed_name_info["CPU"],
            "instance_type": processing_results.get("instance_type", "N/A"),
            "step_per_time": step_per_time,
        }

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
                "cost_per_request", "energy_per_request_wh",
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
        "datetime", "lambda", "mu", "servers", "CPU", "instance_type", "step_per_time", "num_files_averaged"
    ]

    ordered_metric_columns = []
    for prefix in [
        "num_reqs", "ave_total", "ave_wait", "ave_service",
        "window_start", "window_end", "elapsed_time",
        "total_cost", "total_energy_wh",
        "cost_per_time", "energy_per_time_wh_per_sec", "average_power_w",
        "cost_per_request", "energy_per_request_wh",
    ]:
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
