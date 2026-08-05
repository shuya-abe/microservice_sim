import csv
import sys
import re
from collections import defaultdict

def generate_status_csv(instance_csv_file, request_csv_file, timesteps_per_second):
    time_interval = 1 / timesteps_per_second

    # --- 料金定数の定義 ---
    # Serverless (AWS Lambda x86) 1GBメモリ
    LAMBDA_REQ_UNIT_PRICE = 0.20 / 1000000
    LAMBDA_TIERS = [
        (6 * 10**9, 0.0000166667),  # 60億 GB-sまで
        (15 * 10**9, 0.0000150000), # 150億 GB-sまで
        (float('inf'), 0.0000133334) # それ以上
    ]

    # Container (AWS ECS Fargate Linux/x86) 1GBメモリ
    CPU_VCPU_COUNT = 0.25 # 1GB RAMタスクの標準的なvCPU割り当て
    ECS_CPU_PER_HOUR = 0.04048
    ECS_MEM_PER_GB_HOUR = 0.004445

    ECS_CPU_PER_SEC = (ECS_CPU_PER_HOUR / 3600) * CPU_VCPU_COUNT
    ECS_MEM_PER_SEC = (ECS_MEM_PER_GB_HOUR / 3600) * 1.0 # 1GB

    # 1. タイプの判定と初期化
    is_container = "container" in instance_csv_file.lower()
    initial_instance_count = 1 if is_container else 0

    print(f"--- 実行モード: {'コンテナ (ECS)' if is_container else 'サーバレス (Lambda)'} ---")

    # 2. インスタンス変動データの読み込み
    instance_changes = []
    try:
        with open(instance_csv_file, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) # skip header
            for row in reader:
                if row:
                    instance_changes.append((float(row[0]), int(row[2])))
        instance_changes.sort()
        print(f"インスタンス変更ログ: {len(instance_changes)} 件読み込みました。")
    except Exception as e:
        print(f"警告: インスタンスCSVの読み込み中に問題が発生しました（空の可能性があります）: {e}")

    # 3. リクエストデータの読み込み
    requests_data = []
    try:
        with open(request_csv_file, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 実際の処理開始 = start + time_wait
                raw_start = float(row['start'])
                wait = float(row['time_wait'])
                actual_start = raw_start + wait
                end_time = float(row['end'])
                requests_data.append({
                    'id': int(row['id']),
                    'processedBy': row['processedBy'],
                    'raw_start': raw_start,
                    'actual_start': actual_start,
                    'end': end_time
                })
        print(f"リクエストログ: {len(requests_data)} 件読み込みました。")
    except Exception as e:
        print(f"エラー: リクエストCSVの読み込みに失敗しました: {e}")
        return

    # 4. シミュレーション範囲の確定
    # インスタンス変更がない場合も、リクエストの最後までは計算を続ける
    max_time_req = max((req['end'] for req in requests_data), default=0.0)
    max_time_inst = max((c[0] for c in instance_changes), default=0.0)
    max_time = max(max_time_req, max_time_inst)

    if max_time == 0:
        print("エラー: 処理対象のデータ期間が0秒です。")
        return

    # 5. 出力ヘッダと初期化
    base_header = ['timestep', 'time', 'num_request', 'num_processing_request', 'num_instance', 'num_processing_instance']
    if is_container:
        cost_cols = ['cpu_cost_per_step', 'cumulative_cpu_cost', 'memory_cost_per_step', 'cumulative_memory_cost']
    else:
        cost_cols = ['computing_cost_per_step', 'cumulative_computing_cost', 'request_cost_per_step', 'cumulative_request_cost']

    output_header = base_header + cost_cols + ['step_cost', 'total_cost']
    output_rows = []

    curr_instances = initial_instance_count
    idx_change = 0
    time = 0.0
    timestep = 0

    # 累積用変数
    cum_a = 0.0 # Serverless: Computing / Container: CPU
    cum_b = 0.0 # Serverless: Request / Container: Memory
    total_gb_seconds = 0.0 # Lambdaティア判定用

    # 6. メインループ
    while time <= max_time + (time_interval * 0.5):
        # インスタンス数の更新（ログがある場合）
        while idx_change < len(instance_changes) and instance_changes[idx_change][0] <= time:
            curr_instances = instance_changes[idx_change][1]
            idx_change += 1

        num_req_in_system = 0
        num_proc_req = 0
        busy_instances = set()
        step_new_requests = 0

        for req in requests_data:
            # 系内リクエスト（到着済み・未完了）
            if req['raw_start'] <= time < req['end']:
                num_req_in_system += 1

            # 実行中リクエスト（実開始済み・未完了）
            if req['actual_start'] <= time < req['end']:
                num_proc_req += 1
                busy_instances.add(req['processedBy'])

            # このステップで発生したリクエスト料金（実開始タイミングで計上）
            if time <= req['actual_start'] < time + time_interval:
                step_new_requests += 1

        num_proc_inst = len(busy_instances)

        # 料金計算
        if is_container:
            # コンテナ: 起動インスタンス数(curr_instances)に基づく
            step_a = curr_instances * time_interval * ECS_CPU_PER_SEC
            step_b = curr_instances * time_interval * ECS_MEM_PER_SEC
        else:
            # サーバレス: 処理中インスタンス数(num_proc_inst)に基づく
            step_gb_sec = num_proc_inst * time_interval * 1.0
            total_gb_seconds += step_gb_sec

            # ティア判定
            unit_price = LAMBDA_TIERS[0][1]
            for limit, price in LAMBDA_TIERS:
                if total_gb_seconds <= limit:
                    unit_price = price
                    break

            step_a = step_gb_sec * unit_price
            step_b = step_new_requests * LAMBDA_REQ_UNIT_PRICE

        step_total = step_a + step_b
        cum_a += step_a
        cum_b += step_b
        total_accumulated = cum_a + cum_b

        row = [
            timestep,
            f"{time:.4f}",
            num_req_in_system,
            num_proc_req,
            curr_instances,
            num_proc_inst,
            f"{step_a:.12f}", f"{cum_a:.12f}",
            f"{step_b:.12f}", f"{cum_b:.12f}",
            f"{step_total:.12f}", f"{total_accumulated:.12f}"
        ]
        output_rows.append(row)

        time += time_interval
        timestep += 1

    # 7. CSV出力
    output_csv = request_csv_file.replace("_packet.csv", "_status.csv")
    if output_csv == request_csv_file:
        output_csv = request_csv_file.rsplit('.', 1)[0] + "_status.csv"

    try:
        with open(output_csv, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(output_header)
            writer.writerows(output_rows)
        print(f"成功: 結果を '{output_csv}' に書き込みました。 ({timestep} ステップ)")
    except Exception as e:
        print(f"エラー: 書き込み中にエラーが発生しました: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python analyze_status_final.py <instance_csv> <request_csv> <hz>")
        sys.exit(1)

    try:
        hz = int(sys.argv[3])
        generate_status_csv(sys.argv[1], sys.argv[2], hz)
    except ValueError:
        print("エラー: タイムステップ数(Hz)は整数で指定してください。")