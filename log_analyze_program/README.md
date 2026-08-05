# log_analyze_program

シミュレーション出力（`*_packet.csv` / `*_num_instance.csv`）を集計・コスト/電力計算・可視化するスクリプト群です。

シミュレータ本体の詳細はリポジトリ直下の [README.md](../README.md) / [README_JP.md](../README_JP.md) を参照してください。

---

## 依存ライブラリ

```bash
pip install pandas matplotlib numpy
```

---

## 現役スクリプト

| スクリプト | 役割 |
|---|---|
| `log_analyzer_with_cost_and_power.py` | 時系列解析（インスタンス/リクエスト/CPU/コスト/電力） |
| `analyze_status_with_cost.py` | インスタンス単位の稼働状態 + コスト CSV |
| `enhanced_process_result.py` | 複数 `*_packet.csv` を集約し応答時間・コスト・電力を要約 |
| `generate_graphs.py` | 集約 CSV から比較グラフ（PDF）を生成 |

---

## 1. `log_analyzer_with_cost_and_power.py`（主力）

`*_packet.csv` と `*_num_instance.csv` からタイムステップ単位の分析を行い、コストと消費電力を計算します。

主な機能:

- packet / num_instance の時系列集計
- 新旧列名の自動判定
  - packet: `processedBy` / `processed_by`
  - num_instance: `time` / `sim_time`, `num_instances` / `num_hot_instances`
- ファイル名 prefix から CPU 数を抽出して課金計算
- 消費電力（停止・起動中・処理中・アイドル・停止中）
- 変動がない区間の圧縮出力（デフォルト有効）
- フォルダ一括解析・並列実行

### 使い方

```bash
# prefix 指定
python log_analyzer_with_cost_and_power.py <prefix> [<prefix2> ...] --steps_per_second <Hz>

# フォルダ一括（*_packet.csv と対応する *_num_instance.csv があるもの）
python log_analyzer_with_cost_and_power.py --input_dir <dir> --steps_per_second <Hz>
```

主なオプション:

```bash
--workers <N>       # prefix ごとの並列数
--compact_output    # 変動なし区間を圧縮（デフォルト）
--full_output       # 全ステップを出力
```

### 出力

| ファイル | 内容 |
|---|---|
| `{prefix}_analysis.csv` | 時系列の集計・コスト・電力 |
| `{prefix}_instances.pdf` | インスタンス数 |
| `{prefix}_requests.pdf` | リクエスト数 |
| `{prefix}_cpus.pdf` | 総 CPU / 処理中 CPU |
| `{prefix}_costs_cumulative.pdf` | 累積コスト |
| `{prefix}_cost_breakdown.pdf` | コスト内訳 |
| `{prefix}_power_consumption.pdf` | 瞬間電力 (W) |
| `{prefix}_cumulative_power.pdf` | 積算電力量 (Wh) |

---

## 2. `analyze_status_with_cost.py`

instance ログと request ログから、タイムステップごとの稼働状況とコストを CSV 出力します。  
（インスタンス列ごとの状態を見たい場合向け。集約時系列は上記 1. を推奨）

```bash
python analyze_status_with_cost.py <instance_csv> <request_csv> <Hz>
```

出力: `{prefix}_status.csv`

---

## 3. `enhanced_process_result.py`

複数の `*_packet.csv` を一括処理し、抽出割合ごとの応答時間統計に加え、対応する `*_analysis.csv` があればコスト・電力指標も集約します。

主な仕様:

- 「最後のリクエスト生成時刻までに完了したリクエスト」のうち後半 50/40/30/20/10% を対象
- 同一設定（`lambda`, `mu`, `servers`, `CPU`, `instance_type`, `step_per_time`）は平均化
- `*_analysis.csv` が無い入力はコスト/電力列が `N/A`
- 平均結果算出区間（`window_start_*`〜`window_end_*`）内の**時間加重平均インスタンス数** `ave_instances_*` を出力（`*_num_instance.csv` 優先、無ければ `*_analysis.csv` の `num_instances`）
- packet 列名は `processedBy` / `processed_by` 両対応

```bash
python enhanced_process_result.py <packet_csv> [<packet_csv2> ...] <step_per_time>
```

出力: `rev_result_{YYYYMMDDHHMM}.csv`

---

## 4. `generate_graphs.py`

`enhanced_process_result.py` の集約 CSV を入力に、mu ごとの比較グラフを出力します（応答時間・コスト・電力、トレードオフ図など）。

```bash
python generate_graphs.py <rev_result_*.csv>
```

出力例:

- `mu{値}_total.pdf` / `mu{値}_wait.pdf` / `mu{値}_service.pdf`
- コスト・電力系 PDF、トレードオフ図（linear / log など）

---

## 典型的な実行フロー

```bash
# 1. ケースまたはフォルダを詳細解析（コスト + 電力）
python log_analyzer_with_cost_and_power.py --input_dir ../result/<experiment_dir> --steps_per_second 100000

# 2. 複数ケースを集約
python enhanced_process_result.py ../result/<experiment_dir>/*_packet.csv 100000

# 3. 集約結果を可視化
python generate_graphs.py rev_result_*.csv
```

`steps_per_second` はシミュレータの `step_per_time` と同じ値を渡してください。

---

## 削除済み（旧版）

次のスクリプトは機能が現役版に包含されるため削除しました。

| 削除ファイル | 置き換え先 |
|---|---|
| `log_analyzer.py` | `log_analyzer_with_cost_and_power.py` |
| `log_analyzer_with_cost.py` | 同上 |
| `log_analyzer_with_cost_cpu_mem.py` | 同上 |
| `analyze_status.py` | `analyze_status_with_cost.py` |
| `process_result.py` | `enhanced_process_result.py` |
| `generate_graphs_group.py` | `generate_graphs.py` |
| `generate_graphs_group_mono.py` | 同上 |
| `generate_graphs_mu_vs_time_cpu1.py` | 同上 |
