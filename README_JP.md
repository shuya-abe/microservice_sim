# Container / Serverless シミュレータ

> English overview (GitHub): [README.md](README.md)

コンテナ型オートスケーリングとサーバレス（コールドスタート付き）の待ち行列シミュレータです。離散時間ステップでリクエスト到着・振り分け・処理・スケールイン/アウトを進め、応答時間やホットインスタンス数などを CSV に出力します。

エントリポイントは `simulate.py` です。`config_list.csv` の各行を 1 実験設定として読み、複数回繰り返して並列実行します。

本ファイルは詳細仕様書です。概要・Quick Start は [README.md](README.md) を参照してください。

---

## 目次

1. [全体構成と相互関係](#1-全体構成と相互関係)
2. [実行方法](#2-実行方法)
3. [シミュレーションの時間モデル](#3-シミュレーションの時間モデル)
4. [メインループとアルゴリズム](#4-メインループとアルゴリズム)
5. [モジュール詳細](#5-モジュール詳細)
6. [入力ファイル（CSV）](#6-入力ファイルcsv)
7. [出力ファイル（CSV）](#7-出力ファイルcsv)
8. [定数・状態・フラグ](#8-定数状態フラグ)
9. [ファイル一覧](#9-ファイル一覧)

---

## 1. 全体構成と相互関係

```
simulate.py
  └─ Config.initialSetup(config_list の 1 行)
  └─ (必要なら) Generator で requests/*.csv を事前生成
  └─ QueueSimulator
        ├─ Generator …… リクエスト列の生成 / 読込
        ├─ Sender …… 時刻到達したリクエストを Cluster へ投入
        └─ Cluster
              ├─ Balancer …… 未割当リクエストをインスタンスへ振分
              ├─ Scaler …… スケールアウト/イン、コールドスタート、アイドル停止
              └─ Instance (Container | Serverless)
                    ├─ queue (待機キュー)
                    └─ exec_queue (CPU スロット上の実行中リクエスト)
```

### データの流れ（1 ステップ）

1. **Sender** が `start_time * step_per_time <= 現在ステップ` のリクエストを Cluster に渡す  
2. Cluster は **Balancer** の未割当キューに積む  
3. **Balancer** がインスタンスを選び、インスタンスの待機キューへ転送  
4. **Scaler** が（モードに応じて）スケール判断やアイドル停止を行う  
5. 各 **Instance** が CPU スロットでワークロードを減算し、完了リクエストを返す  
6. **QueueSimulator** が完了リクエストを集計用リストに登録  

### コンポーネントの役割

| コンポーネント | 役割 |
|---|---|
| `simulate.py` | 実験ランナー。設定読込、リクエスト事前生成、プロセス並列、オートチューニング、サマリ CSV 追記 |
| `config.py` | `config_list.csv` 1 行 → 実行時パラメータ・入出力パス |
| `queue_simulator.py` | 離散時間シミュレーション本体。ハイブリッドスキップ、結果集計 |
| `generator.py` | ポアソン到着・指数サービス時間のリクエスト生成 / CSV I/O |
| `sender.py` | 生成済みリクエストをシミュレーション時刻に沿って投入 |
| `cluster.py` | クラスタ CPU 上限管理、Balancer / Scaler / Instance の束ね |
| `balancer.py` | リクエスト振分（コンテナ: 空きキュー優先、サーバレス: hottest / cold start） |
| `scaler.py` | コンテナ: CPU 利用率ベースのスケール。サーバレス: アイドルタイムアウト |
| `instance.py` | インスタンス共通（キュー、実行スロット、セットアップ/シャットダウン） |
| `container.py` / `serverless.py` | 起動完了条件・処理時の最終利用時刻更新などの差分 |
| `request.py` | リクエスト状態と時刻・ワークロード |

---

## 2. 実行方法

### 依存関係のインストール

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

- シミュレータ本体: `numpy`
- `log_analyze_program/`: `pandas`, `matplotlib`

### シミュレーション実行

```bash
python simulate.py
```

実行時の挙動は `simulate.py` 先頭の `SETTINGS` で制御します（環境変数は使いません）。

| キー | 意味 | 既定例 |
|---|---|---|
| `config_file` | 実験設定 CSV | `config_list.csv` |
| `sim_count_start` / `sim_count_end` | 繰り返し添字 `[start, end)` | `0`〜`10`（10 回） |
| `autotune_enabled` | ワーカー数の自動選定 | `True` |
| `autotune_only` | オートチューンのみで本実験をスキップ | `False` |
| `autotune_profile_sim_time` | プロファイル1本の論理時間目安（完了数 `≈ λ×t` に換算） | `30` |
| `autotune_profile_max_lambda` | プロファイルに使う λ の上限（1600 等は除外） | `200` |
| `autotune_profile_max_requests` | プロファイル1本の最大完了数 | `5000` |
| `generate_requests_only` | 共有リクエスト CSV の事前生成だけ行い本実験をスキップ（並列） | `False` |

CLI: `python simulate.py --generate-requests-only` でも同じ動作になります（SETTINGS の値にかかわらず生成のみ）。
| `max_workers` | 固定ワーカー数（`None` なら既定ポリシー） | `None` |
| `reserved_cores` | ホスト用に残すコア数 | `4` |
| `host_cores` | WSL 時のホストコア上限ヒント | `20` |
| `enable_hybrid_skip` | アイドル区間のステップ飛ばし | `True` |
| `enable_scale_check_skip` | コンテナの periodic scale チェックが no-op なら次到着まで飛ばす | `True` |
| `steady_enabled` | シミュレータ内定常判定まで継続 | `True` |
| `steady_batch_reqs` | 1 バッチあたり最低完了リクエスト数 | `10000` |
| `steady_batch_min_time` | 1 バッチ最低論理時間（`None` なら serverless=timer / container=4×scale_interval） | `None` |
| `steady_rel_tol` | 連続バッチ平均の相対許容差 | `0.05` |
| `steady_consecutive` | 定常とみなす連続安定バッチ数 | `3` |
| `steady_max_batches` | バッチ数の上限（安全弁） | `50` |
| `steady_ci_level` | バッチ平均の信頼水準 | `0.95` |
| `steady_preextend_enabled` | 定常に必要な到着長の目安まで共有 CSV を事前延長 | `True` |
| `steady_preextend_batches` | 事前延長のバッチ数目安（`None` なら `max(3K, K+10)`） | `None` |
| `steady_preextend_margin` | 目安時間への安全係数 | `1.1` |
| `steady_preextend_max_rows` | ファイルあたり事前生成行数の上限（超過分はオンライン追記） | `2000000` |

### 並列実行の流れ

1. `config_list.csv` からコメント行（先頭 `#`）以外を読み込む  
2. 各 `(sim_index, config_row)` をタスクとする  
3. 既に `OUTPUT_FILE`（`*_result.csv`）が非空ならそのタスクはスキップ（再開用）  
4. 必要な `requests/*.csv` をメインプロセスで事前生成（ワーカー間の競合回避）  
5. `ProcessPoolExecutor` で各タスクが `simulate(config)` を実行  
6. 完了ごとにサマリ行を `SIM_DEFAULT_OUTPUT_FILE` へ追記  

### オートチューニング

小さなプロファイル実行で設定ごとの実行時間中央値を測り、LPT（Largest Processing Time）でメイクスパンを予測してワーカー数を選びます。

---

## 3. シミュレーションの時間モデル

- **論理時間** `t`（秒相当）と **離散ステップ** `s` の関係:  
  `s = t * SIM_STEP_PER_TIME`（コード上は `step / step_per_time` で時間へ戻す）
- 1 ステップで各実行中リクエストのワークロードは  
  `processing_capacity = CONFIG_DEFAULT_CAPACITY / SIM_STEP_PER_TIME`  
  だけ減る
- サービス時間の期待値は指数分布 `Exp(mu)`。ワークロードは  
  `workload = CONFIG_DEFAULT_CAPACITY * service_time`  
  のため、処理完了までの論理時間はおおよそ `service_time` になる
- 到着間隔は指数分布 `Exp(lambda)`（`scale = 1/lambda`）

### 終了条件（`SIM_LIMIT`）

| `limit` 値 | 定数 | 終了条件 |
|---|---|---|
| `req` | `LIMIT_REQUEST` | 完了リクエスト数が `threshold` に達するまで（定常モード OFF 時） |
| `step` | `LIMIT_TIMESTEP` | ステップが `threshold` 以上 **かつ** Sender の全リクエストを投入・処理し終えるまで |
| `time` | `LIMIT_TIME` | 論理時間が `threshold` 以上 **かつ** 全リクエスト処理完了まで |

### 定常モード（`steady_enabled=True`）

`simulate.py` の `SETTINGS` で有効化します。高 λ でも serverless のアイドルタイマ（例: 600）分の過渡をまたいで計測するため、**固定 threshold では止めず**、バッチ計測で定常化するまで走らせます。

到着列は比較のため **オフライン CSV が正** です。同一 `(threshold, λ, μ, sim_index)` の構成（container / serverless など）は同じファイルを読みます。起動時に定常到達の目安時間

`horizon ≈ steady_preextend_batches × max(batch_min_time, batch_reqs/λ) × margin`

（行数は `steady_preextend_max_rows` で上限）まで事前延長し、それでも足りない場合だけロック付きで追加生成して **同じ CSV に追記** します。後から走った構成や並列ワーカーは追記分を再利用するので、システム差だけを比較できます。本実験の投入順は `config_list.csv` の行順です。定常バッチ完了は親プロセスが `[steady] repeat=...` として表示します。

**バッチ定義（ハイブリッド）**

1 バッチは次の **両方** を満たすまで継続します。

- 完了リクエスト数 ≥ `steady_batch_reqs`
- バッチ壁時計（論理時間）≥ `steady_batch_min_time`  
  - 未指定時: serverless / warm-wait → `serverless_timer`、container → `4 * scale_interval`

**安定判定**

各バッチで系内時間・待機時間・時間加重平均ホット台数の平均と（応答時間系は）95% CI を計算します。連続 `steady_consecutive` バッチについて、各指標で

- 相対差 ≤ `steady_rel_tol`、または
- 95% CI が交差（台数は相対差のみ）

なら定常到達とします。採用値は **その連続 K バッチを結合した平均** です。`steady_max_batches` に達した場合は `steady_reached=false` で末尾 K バッチを採用して終了します。

**出力の意味**

`ex_time_*` / `ave_instances_steady` は全期間平均ではなく **定常区間の値** です。`steady_start` / `steady_end` がその区間です。事後の「末尾 50%…」推定は不要で、`log_analyze_program/enhanced_process_result.py` は companion の `*_result.csv` に定常窓があればそれを使います（無い旧結果のみ従来の％抽出）。

---

## 4. メインループとアルゴリズム

### 4.1 1 ステップの処理順（`QueueSimulator.simulateStep`）

```
Sender.runStep
  → Balancer.runStep（manageQueue）
  → Scaler.runStep
  → 各 Runnable Instance.runStep
```

### 4.2 ハイブリッドスキップ（`enable_hybrid_skip`）

イベントが「今すぐ起きない」ステップでは、次イベントまで一気に進めます。

1. `hasImmediateEvent(step)` が真ならスキップしない  
2. そうでなければ `getNextEventStep(step)` で次イベント候補の最小ステップを取る  
3. `advanceBusyWork(skip_steps)` でセットアップ/シャットダウンタイマーと実行中ワークロードを一括更新  
4. `timestep` をその分加算  

**次イベント候補の例**

- 次リクエスト到着ステップ  
- コンテナの次スケールチェック時刻（`SCALE_INTERVAL * STEP_PER_TIME` の倍数。**ただし** `enable_scale_check_skip=True` かつ単一 ACTIVE が完全アイドルなら候補から除外）  
- SETUP / SHUTDOWN 完了時刻  
- サーバレスのアイドルタイムアウト  
- 実行中リクエストの処理完了見積もり  

### 4.3 リクエスト振分（`Balancer`）

#### コンテナモード（`FLG_CONTAINER`）

- ACTIVE / WORKING かつ **待機キュー長 0** のインスタンスを先頭から探す  
- 見つからなければそのステップでは未割当のまま残す（スケールアウト待ち）

#### サーバレスモード（`FLG_SERVERLESS`）

1. **hottest**: ACTIVE かつキュー長 0 のうち、`last_time` が最大のものを選ぶ  
2. いなければ **coldStart**: Scaler 経由で INACTIVE を起動し、そのインスタンスへ割当  

#### サーバレス warm-wait モード（`FLG_SERVERLESS_WARM_WAIT` / `instance_flg=serverless_warm_wait`）

スケールパーリクエストのコールドスタートを常に行う代わりに、セットアップ時間 `S`・当該リクエストのバランサー内位置 `p`・サービス率 `μ`・ウォーム CPU スロット数 `W` から

```
expected_wait ≈ p / (W * μ)
```

を見積もり、`expected_wait ≤ S`（すなわち `p ≤ S·W·μ`）ならコールドスタートせずウォーム空きを待つ。空きのない SETUP があればそこへ割当。`W=0` のときは従来どおりコールドスタートする。バランサーに未割当がある間はアイドル停止を延期する。 

### 4.4 スケーリング（`Scaler`）

#### コンテナ（周期チェック）

チェック間隔: `CONFIG_SCALE_INTERVAL * SIM_STEP_PER_TIME` ステップごと（step 0 は除外）。

メトリクス:

```
cpu_util = Σ(インスタンスCPU利用率) / num_active
ideal_instance = cpu_util / CONFIG_SCALE_TARGET
```

各インスタンスの利用率:

```
CpuCtr / (SCALE_INTERVAL * STEP_PER_TIME * num_CPU)
```

（チェック後に `CpuCtr` は 0 にリセット）

| 条件 | 動作 |
|---|---|
| `metrics - 1 > SCALE_SENSITIVE` | **scaleOut**: 目標台数まで INACTIVE/SHUTDOWN を起動、またはシャットダウン中をキャンセル |
| `1 - metrics > SCALE_SENSITIVE` | **scaleIn**: 末尾側から ACTIVE/WORKING をシャットダウン開始（最低 1 台は維持） |

#### サーバレス

周期スケールは行わない。ACTIVE で  
`timestep - last_time >= SERVERLESS_TIMER * STEP_PER_TIME`  
ならアイドル停止（SHUTDOWN へ）。需要時は Balancer の cold start で起動。

### 4.5 インスタンス状態機械

```
INACTIVE ──activate──► SETUP ──setup完了──► ACTIVE
                                              │
                         リクエスト処理中 ◄───┤──► WORKING
                                              │
                    deactivate / idle timeout ▼
                                         SHUTDOWN ──完了──► INACTIVE
```

| 状態 | 意味 |
|---|---|
| `INACTIVE` | 停止。Runnable リスト外 |
| `SETUP` | 起動中。`setuptimer` を減算 |
| `ACTIVE` | 稼働・アイドル |
| `WORKING` | リクエスト処理中 |
| `SHUTDOWN` | 停止処理中。`deactivatetimer` を減算 |

**セットアップ時間の差**

- Container: `SETUPTIME * STEP_PER_TIME` ステップ後、`setuptimer < 0` で ACTIVE。完了時に Balancer へ登録  
- Serverless: `SETUPTIME * STEP_PER_TIME + 1`、完了条件は `setuptimer <= 0`。cold start 時は起動開始と同時に Balancer 登録済み  

**初期台数**

- `CONFIG_DEFAULT_FLG == True` のとき `CONFIG_DEFAULT_NUM` 台を生成  
- 先頭 `CONFIG_DEFAULT_START_INSTANCES` 台は ACTIVE、残りは `CONFIG_DEFAULT_STATUS`（多くは inactive）  
- 未指定時の既定: コンテナは 1 台、サーバレスは 0 台から開始  

クラスタ合計 CPU が `CONFIG_CLUSTER_CPU` を超えるインスタンス追加は拒否されます。

### 4.6 リクエスト処理（`Instance.processRequests`）

- CPU 数ぶんの `exec_queue` スロット  
- スロットが空なら待機キュー先頭を投入  
- 毎ステップ `workload -= processing_capacity`  
- `workload <= 0` の次ステップで FINISHED とし、終了時刻を記録  
- 処理中は `CpuCtr` を加算（スケールメトリクス用）  
- Serverless は処理のたびに `last_time` を更新（アイドル判定用）  

キュー上限 `CONFIG_DEFAULT_QUEUE_LENGTH`:

- `-1`: 無制限  
- `0` 以上: 満杯なら `DROP`（完了集計には通常入らない）  

---

## 5. モジュール詳細

### `simulate.py`

- `main()`: 設定読込 →（任意）オートチューン → 全タスク並列実行  
- `simulate(config)`: `QueueSimulator` を起動し、個別結果 CSV を書いてサマリ dict を返す  
- `ensure_request_file_exists` / `precreate_request_files`: リクエスト CSV の事前生成  

### `config.py` — `Config.initialSetup(row, sim_index)`

CSV 行から全パラメータを構築し、入出力パスを決定します。

**2 つの列フォーマットを自動判定**

1. **新形式**: 先頭に `experiment_id` があり、かつ `limit` 列（4 列目）が `req`/`time`/`step`  
2. **旧形式**: `experiment_id` なし（テスト用 CSV など）  

さらに `default_start_instances` 列の有無も、後ろの `default_status` 位置から推定します。

生成される主なパス:

| 属性 | 内容 |
|---|---|
| `CONFIG_REQUEST_FILE` | `./requests/{threshold}{sec\|step\|reqs}_lambda{λ}_mu{μ}_{sim_index}.csv` |
| `OUTPUT_FILE` | `./result/{experiment_id}_{N}srv_{cpu}CPU_{threshold}{time\|step\|req}_lambda{λ}_mu{μ}_{container\|serverless}_{sim_index}_result.csv` |
| `OUTPUT_FILE_PACKET` | 上記ベース + `_packet.csv` |
| `OUTPUT_FILE_NUM_INSTANCE` | 上記ベース + `_num_instance.csv` |
| `SIM_DEFAULT_OUTPUT_FILE` | 設定 CSV で指定したサマリ追記先 |

### `generator.py`

- `createAllRequests`: 終了条件に達するまで到着・ワークロードをサンプリング  
- `extendUntil` / `ensure_file_until`: 共有 CSV を先読みし、不足分だけ生成して追記（並列時は CSV 本体に `flock`。sidecar の `.lock` は作らない）
- `calculateNextRequest`: 到着間隔 `floor(Exp(1/λ) * step_per_time) / step_per_time`  
- `calculateWorkload4Request`: `capacity * Exp(1/μ)`  
- `outputRequests` / `inputRequests` / `appendRequests`: CSV 書き出し・読込・追記  

### `sender.py`

- 開始時刻をステップ境界に丸め: `ceil(start * step_per_time) / step_per_time`  
- 各ステップで到着済みリクエストを `cluster.addRequest`  

### `queue_simulator.py` の結果集計

完了リクエストについて:

- `time_lifetime = end - start`  
- `time_wait = time_start_process - start`  
- `time_service = lifetime - wait`  

平均:

- `ex_time_service`, `ex_time_wait`, `ex_time_total`（いずれも完了リクエスト数で割った平均）  

---

## 6. 入力ファイル（CSV）

### 6.1 `config_list.csv`（実験設定）

1 行目はヘッダ。2 行目以降が実験。先頭が `#` の行はスキップされます。

#### 新形式（現行の `config_list.csv`）

| 列 | 名前 | 内容 |
|---|---|---|
| 0 | `experiment_id` | 実験 ID。出力パスのプレフィックスにも使用（英数字と `_` 以外は `_` に置換） |
| 1 | `threshold` | 終了閾値（リクエスト数 / ステップ数 / 時間） |
| 2 | `step_per_time` | 論理時間 1 あたりのステップ数 |
| 3 | `limit` | `req` / `time` / `step` |
| 4 | `cluster_cpu` | クラスタの合計 CPU 上限 |
| 5 | `lambda` | 到着率 λ |
| 6 | `mu` | サービス率 μ |
| 7 | `request_flg` | `input`: 既存リクエスト CSV を使う想定 / それ以外: 生成側フラグ（実体はファイル有無で分岐） |
| 8 | `scale_sensitive` | スケール感度（`|metrics-1|` がこれより大きいとき反応） |
| 9 | `scale_interval` | コンテナのスケールチェック間隔（論理時間） |
| 10 | `scale_target` | 目標 CPU 利用率 |
| 11 | `serverless_timer` | サーバレスのアイドル停止時間（論理時間） |
| 12 | `instance_flg` | `container` / `serverless` / `serverless_warm_wait`（別名 `serverless_wait`） |
| 13 | `default_flg` | 真なら同一スペックを `default_instance_num` 台生成 |
| 14 | `default_instance_num` | 生成台数上限（プールサイズ） |
| 15 | `default_start_instances` | 初期 ACTIVE 台数 |
| 16 | `default_setuptime` | 起動所要（論理時間） |
| 17 | `default_shutdowntime` | 停止所要（論理時間） |
| 18 | `default_capacity` | インスタンス処理能力（論理時間あたりのワークロード処理量） |
| 19 | `default_num_cpu` | インスタンスあたり CPU 数（並列実行スロット数） |
| 20 | `default_queue_length` | 待機キュー上限。`-1` で無制限 |
| 21 | `default_status` | 初期非起動分の状態 `inactive` / `active` |
| 22 | `sim_flg` | `verbose` / `simple`（現状の集計経路は verbose 相当） |
| 23 | `sim_default_output_file` | 全実験共通のサマリ CSV パス |

#### 旧形式（`config_list_test_*.csv`）

`experiment_id` と `default_start_instances` がなく、先頭が `threshold` です。  
`EXPERIMENT_ID` は `legacy_{sim_index}`、初期 ACTIVE 台数はモード既定（container=1, serverless=0）になります。

### 6.2 `requests/*.csv`（リクエスト列）

**生成タイミング**

- メインプロセスの `precreate_request_files`、またはシミュレータ初期化時にファイルが無い場合  
- `Generator.createAllRequests` → `outputRequests`

**読込タイミング**

- `QueueSimulator.settingSimulate` でファイルが存在するとき `inputRequests`

| 列 | 名前 | 内容 |
|---|---|---|
| 0 | `id` | リクエスト ID（0 始まり） |
| 1 | `workload` | 初期ワークロード（`capacity * Exp(1/μ)`） |
| 2 | `start` | 到着論理時刻 |

ファイル名例: `100000reqs_lambda100.0_mu100.0_0.csv`  
（`{threshold}{reqs|step|sec}_lambda{λ}_mu{μ}_{sim_index}.csv`）

同一 `(threshold, λ, μ, sim_index)` ならコンテナ実験とサーバレス実験で同じリクエスト列を共有できます。定常モードで列が足りなくなればそのファイルへ追記し、他構成も追記後の列を使います。比較の前提は「到着過程を揃えてシステム側だけ変える」ことです。

---

## 7. 出力ファイル（CSV）

1 回のシミュレーション（1 タスク）で主に次の 3 ファイルが書き出され、さらにランナーがサマリを追記します。

### 7.1 `*_result.csv`（個別集計）

**パス**: `Config.OUTPUT_FILE`  
**書き出しタイミング**: `simulate()` 内。シミュレーション終了直後に **上書き作成**（ヘッダ + 結果 1 行）。

| 列 | 内容 |
|---|---|
| `step_per_time` | ステップ粒度 |
| `total_time` | 終了時の論理時間（`num_steps / step_per_time`） |
| `num_steps` | 総ステップ数 |
| `num_reqs` | 定常モード時は採用定常区間の完了数、それ以外は全完了数 |
| `ex_time_service` / `ex_time_wait` / `ex_time_total` | 平均サービス / 待ち / 滞在（定常モード時は定常区間） |
| `steady_enabled` | 定常モードの有無 |
| `steady_reached` | 連続安定バッチ条件を満たしたか |
| `num_batches` / `steady_batch_index` | 実施バッチ数 |
| `steady_start` / `steady_end` | 採用定常区間の論理時刻 |
| `ci_*_low` / `ci_*_high` | 定常区間の応答時間系 95% CI |
| `ave_instances_steady` | 定常区間の時間加重平均ホット台数 |

既に非空ファイルがあるタスクはランナーがスキップします。

### 7.2 `*_packet.csv`（リクエスト単位の詳細）

**パス**: `Config.OUTPUT_FILE_PACKET`  
**書き出しタイミング**:

1. **初期化時**（`settingSimulate`）: ヘッダだけ空ファイルとして作成  
2. **定常モード**: 完了のたびに追記（メモリ節約のためリクエストオブジェクトは保持しない）  
3. **非定常モード・終了時**（`calcTotalTimeVerbose`）: ヘッダ付きで **全完了リクエストを再書き込み**

| 列 | 内容 |
|---|---|
| `id` | リクエスト ID |
| `processed_by` | 処理インスタンス（`container{N}` / `serverless{N}`） |
| `workload` | 元ワークロード（`org_workload`） |
| `start` | 到着時刻 |
| `end` | 完了時刻 |
| `time_lifetime` | `end - start` |
| `time_wait` | `time_start_process - start` |
| `time_service` | `lifetime - wait` |

### 7.3 `*_num_instance.csv`（ホットインスタンス数の変化）

**パス**: `Config.OUTPUT_FILE_NUM_INSTANCE`  
**書き出しタイミング**: `startSimulate` のループ中。  
**条件**: ホットインスタンス数（ACTIVE または WORKING）が **直前と変化したときのみ** 1 行追記。

| 列 | 内容 |
|---|---|
| `sim_time` | 論理時間（`step / step_per_time`） |
| `step` | ステップ番号 |
| `num_hot_instances` | ホット（ACTIVE/WORKING）台数 |

シミュレーション開始時にヘッダを書いてからループに入ります。

### 7.4 サマリ CSV（`SIM_DEFAULT_OUTPUT_FILE`）

**書き出しタイミング**: 各ワーカー完了後、メインプロセスが **追記**。  
ファイルが無い／空なら先にヘッダを書きます。

| 列 | 内容 |
|---|---|
| `timestamp` | 完了時刻（`datetime.now()`） |
| `request_file` | 使用したリクエスト CSV パス |
| `lambda` | λ |
| `mu` | μ |
| `num_instances` | クラスタに登録されたインスタンス総数（プールサイズ） |
| `default_capacity` | 既定 capacity |
| `default_num_cpu` | 既定 CPU 数 |
| `step_per_time` | ステップ粒度 |
| `total_time` | 論理総時間 |
| `num_steps` | 総ステップ |
| `num_reqs` | 完了リクエスト数 |
| `ex_time_service` | 平均サービス時間 |
| `ex_time_wait` | 平均待ち時間 |
| `ex_time_total` | 平均滞在時間 |

### 7.5 出力タイミングまとめ

```
[タスク開始]
  settingSimulate
    ├─ requests/*.csv 読込 or 生成
    └─ *_packet.csv をヘッダのみ作成

  startSimulate
    └─ 毎ステップ（変化時） *_num_instance.csv に追記

  endSimulate
    └─ *_packet.csv を全リクエストで上書き
    └─ 平均指標を計算

[simulate() 側]
  └─ *_result.csv を上書き

[メインプロセス]
  └─ SIM_DEFAULT_OUTPUT_FILE にサマリ 1 行追記
```

> 注: `result/` 配下の `*_analysis.csv` や `rev_result_*.csv` などは、本ディレクトリ直下のシミュレータ本体ではなく、`log_analyze_program/` 内の後処理スクリプト由来の成果物です。

---

## 8. 定数・状態・フラグ

### `limit.py` — 終了条件

| 定数 | 値 | 意味 |
|---|---|---|
| `LIMIT_DEFAULT` | 0 | 未設定（即 return） |
| `LIMIT_REQUEST` | 1 | リクエスト数 |
| `LIMIT_TIMESTEP` | 2 | ステップ数 |
| `LIMIT_TIME` | 3 | 論理時間 |

### `sim_flg.py` — モードフラグ

| 定数 | 意味 |
|---|---|
| `FLG_DEFAULT` / `FLG_VERBOSE` | 出力詳細度 |
| `FLG_OUTPUT` / `FLG_INPUT` | リクエスト生成 vs 既存ファイル利用の意図 |
| `FLG_CONTAINER` / `FLG_SERVERLESS` / `FLG_SERVERLESS_WARM_WAIT` | インスタンス種別 |

### `status.py` — リクエスト / インスタンス状態

**リクエスト**: `GENERATED` → `UNASSIGNED` → `QUEUEING` → `PROCESSING` → `FINISHED`（満杯時 `DROP`）  

**インスタンス**: `INACTIVE` / `SETUP` / `ACTIVE` / `WORKING` / `SHUTDOWN`

### `constant.py`

`Limit` / `Flg` / `Status` の基底クラス（マーカー）。

### `main.py` / `__init__.py`

空ファイル（現状未使用）。実行は `python simulate.py` を使います。

---

## 9. ファイル一覧

| ファイル | 概要 |
|---|---|
| `simulate.py` | エントリポイント・並列実行・オートチューン |
| `queue_simulator.py` | シミュレーションエンジン |
| `steady_state.py` | 定常判定（バッチ平均・CI・連続安定） |
| `config.py` | 設定パースとパス生成 |
| `generator.py` | リクエスト生成・CSV I/O |
| `sender.py` | 時刻駆動のリクエスト投入 |
| `cluster.py` | クラスタ（CPU 上限・構成要素のハブ） |
| `balancer.py` | ロードバランサ |
| `scaler.py` | オートスケーラ |
| `instance.py` | インスタンス基底 |
| `container.py` | コンテナ実装 |
| `serverless.py` | サーバレス実装 |
| `request.py` | リクエストエンティティ |
| `status.py` / `limit.py` / `sim_flg.py` / `constant.py` | 列挙定数 |
| `config_list.csv` | 本実験用設定一覧 |
| `config_list_test_before.csv` / `config_list_test_after.csv` | 旧形式のテスト設定 |
| `requests/` | リクエスト入力（および生成物） |
| `result/` | シミュレーション出力 |

---

## 補足: コンテナとサーバレスの比較ポイント

| 観点 | Container | Serverless |
|---|---|---|
| 初期ホット台数（既定） | 1 | 0 |
| スケールアウト | 周期メトリクス（CPU 利用率） | リクエスト時 cold start |
| スケールイン | 周期メトリクス（最低 1 台維持） | アイドルタイマー |
| 振分 | キュー空の ACTIVE/WORKING を探索 | hottest、なければ cold start |
| セットアップ完了 | `setuptimer < 0`、完了時に LB 登録 | `setuptimer <= 0`、cold start 時は先に LB 登録 |
| `last_time` | 未使用 | 処理時に更新、アイドル判定に使用 |
