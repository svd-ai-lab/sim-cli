<div align="center">

<img src="../assets/banner.svg" alt="sim — すべてのエンジニアリングツールを Agent ネイティブに" width="820">

<br>

**すべてのエンジニアリングツールを、Agent ネイティブに。**

*今日の CAD / CAE ソフトウェアは、GUI をクリックするエンジニアのために作られた。*
*明日のユーザーは LLM エージェントで ── 彼らには入り口が必要だ。*

<p align="center">
  <a href="#-クイックスタート"><img src="https://img.shields.io/badge/Quick_Start-2_min-3b82f6?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-ソルバーレジストリ"><img src="https://img.shields.io/badge/Solvers-growing_registry-22c55e?style=for-the-badge" alt="Growing solver registry"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8b5cf6?style=for-the-badge" alt="Companion skills"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click_8-blue" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/transport-HTTP%2FJSON-orange" alt="HTTP/JSON">
  <img src="https://img.shields.io/badge/status-alpha-f97316" alt="Status: alpha">
</p>

[English](../README.md) · [Deutsch](README.de.md) · **日本語** · [中文](README.zh.md)

[sim が存在する理由](#-sim-が存在する理由) · [クイックスタート](#-クイックスタート) · [デモ](#-デモ) · [コマンド](#-コマンド) · [ソルバー](#-ソルバーレジストリ) · [Skills](https://github.com/svd-ai-lab/sim-skills)

</div>

---

## 📰 News

- **2026-04-07** 🚀 **sim-cli v0.2.0** ── GitHub で初の公開リリース。`svd-ai-lab/ion @ feature/openfoam-driver` のリブランド。現在のドライバーレジストリは CFD、マルチフィジックス、熱解析、構造前処理、電池モデリングに広がっており、今後も継続的に拡張されます。
- **2026-04-07** 🧠 コンパニオンリポジトリ [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) を公開 ── Anthropic スキルフォーマットのソルバー別エージェントスキル。LLM が事前知識なしで新しいバックエンドを駆動できます。

---

## 🤔 sim が存在する理由

LLM エージェントは PyFluent、MATLAB、COMSOL、OpenFOAM のスクリプトの書き方を既に知っています ── トレーニングデータに満ちています。彼らに欠けているのは、**ソルバーを起動し、一歩ずつ駆動し、各ステップの間に結果を観察してから**次の手を決めるための標準的な方法です。

今日の選択肢はどれも不十分です：

- **撃ちっぱなしスクリプト** ── エージェントが 200 行を書いて全体を実行、30 行目のエラーが 200 行目にゴミとして現れ、内省もリカバリもできない。
- **ソルバーごとの自作ラッパー** ── すべてのチームが同じ launch / exec / inspect / teardown サイクルを別の形で再発明する。
- **クローズドなベンダー接着剤** ── 組み合わせられず、共通語彙もなく、HTTP も話さないベンダー SDK。

`sim` は欠けていたその層です：

- **一つの CLI**、一つの HTTP プロトコル、CFD・マルチフィジックス・熱・前処理・電池モデルなどをカバーする**成長し続けるドライバーレジストリ**。
- **持続セッション** ── エージェントが各ステップの間に内省できる。
- **リモートファースト** ── CLI クライアントと実際のソルバーは別のマシンに置ける（LAN、Tailscale、HPC ヘッドノードなんでも）。
- **コンパニオンエージェントスキル** ── LLM に各バックエンドを安全に駆動する方法を教える。

> コンテナランタイムが Kubernetes とコンテナの対話を標準化したように、**sim** はエージェントとエンジニアリングソフトウェアの対話を標準化します。

---

## 🏛 アーキテクチャ

<div align="center">
  <img src="../assets/architecture.svg" alt="sim アーキテクチャ: CLI クライアントが HTTP/JSON 経由で、ライブソルバーセッションを保持する sim serve (FastAPI) プロセスと通信する" width="900">
</div>

同じ CLI から 2 つの実行モード、どちらも同じ `DriverProtocol` を共有：

| モード | コマンド | 使いどころ |
|---|---|---|
| **持続セッション** | `sim serve` + `sim connect / exec / inspect` | ステップ間で内省したい、長時間・有状態のワークフロー |
| **ワンショット** | `sim run script.py --solver X` | `.sim/runs/` に採番 run として保存したい、スクリプト全体のジョブ |

ドライバープロトコル、サーバーエンドポイント、実行パイプラインの詳細は [CLAUDE.md](../CLAUDE.md) を参照。

---

## 🚀 クイックスタート

```bash
# 1. ソルバーが入っているマシン（例: Fluent ワークステーション）で
#    まずは sim 本体だけインストール ── まだ SDK は選びません:
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"

# 2. sim にこのマシンを見てもらい、適切な SDK profile を選ばせます:
sim check fluent
# → 検出された Fluent と、それに対応する profile を報告します

# 3. その profile env を立ち上げる（.sim/envs/<profile>/ に固定 SDK 入り
#    の隔離 venv を作る。ステップ 5 で --auto-install を渡せばここは省略可）:
sim env install pyfluent_0_38_modern

# 4. サーバーを起動する（クロスマシン用途のときだけ必要）:
sim serve --host 0.0.0.0          # FastAPI、ポート 7600

# 5. エージェント / ノート PC / ネットワーク内のどこからでも:
sim --host <server-ip> connect --solver fluent --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← まずこれ
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

これが完全なループ：**検出 → bootstrap → 起動 → 駆動 → 観察 → 撤収** ── エンジニアは必要に応じてソルバー GUI をリアルタイムで監視できます。

> **なぜ bootstrap が必要？** (Solver, SDK, driver, skill) の各組み合わせはそれぞれ独立した
> 互換性ユニバースです ── Fluent 24R1 は PyFluent 0.37.x、Fluent 25R2 は 0.38.x が必要。
> sim はそれぞれを隔離された "profile env" として扱うので、同じマシン上に依存衝突なしで両方の
> バージョンを置けます。完全な設計は
> [`docs/architecture/version-compat.md`](architecture/version-compat.md) にあります。

---

## 🎬 デモ

> **録画準備中。** 実際の Fluent セッションに対する `sim connect → exec → inspect → screenshot` の短いターミナルキャプチャがここに入ります。録画する正確なシーケンス：
>
> ```bash
> sim serve --host 0.0.0.0
> sim --host <ip> connect --solver fluent --mode solver --ui-mode gui --auto-install
> sim --host <ip> inspect session.versions    # ← step 0: 今どの profile？
> sim --host <ip> exec "solver.settings.file.read_case(file_name='mixing_elbow.cas.h5')"
> sim --host <ip> exec "solver.settings.solution.initialization.hybrid_initialize()"
> sim --host <ip> exec "solver.settings.solution.run_calculation.iterate(iter_count=20)"
> sim --host <ip> inspect session.summary
> sim --host <ip> disconnect
> ```
>
> 録画を貢献したい？ [`vhs`](https://github.com/charmbracelet/vhs) か [`asciinema`](https://asciinema.org/) を使って `assets/demo.gif` に PR をどうぞ。

---

## ✨ 特徴

### 🧠 エージェントのために設計
- **持続セッション**がスニペットをまたいで生存 ── タスク中にソルバーが再起動することはありません
- **ステップバイステップの内省** ── 各アクションの間に `sim inspect`
- **事前チェック `sim lint`** ── 起動前に欠けた import や未対応 API を捕捉
- **採番ラン履歴**を `.sim/runs/` に保存、`sim logs` で閲覧

### 🔌 ソルバー非依存
- **一つのプロトコル** (`DriverProtocol`) ── 各ドライバーは ~200 LOC、`drivers/__init__.py` で登録
- **持続 + ワンショット**が同じ CLI から ── モードごとに別クライアントは不要
- **オープンレジストリ** ── 新しいソルバーが継続的に追加される。CFD、マルチフィジックス、熱、前処理、電池モデル、すべてスコープ内
- **コンパニオンスキル** [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) ── LLM に各バックエンドの落とし穴を即座に教える

### 🌐 リモートフレンドリー
- **HTTP/JSON トランスポート** ── `httpx` が動くところならどこでも動く
- **クライアント / サーバー分離** ── エージェントはノート PC、ソルバーは HPC ノード、GUI はワークステーション
- **Tailscale 対応** ── クロスネットワークメッシュ展開のために設計

---

## ⚙️ コマンド

| コマンド | 機能 | アナロジー |
|---|---|---|
| `sim check <solver>` | インストールを検出し profile を解決 | `docker info` |
| `sim env install <profile>` | profile env を立ち上げる（venv + 固定 SDK） | `pyenv install` |
| `sim env list [--catalogue]` | 立ち上げ済みの env（または全カタログ）を表示 | `pyenv versions` |
| `sim env remove <profile>` | profile env を撤去 | `pyenv uninstall` |
| `sim serve` | HTTP サーバー起動（クロスマシン用途で必要） | `ollama serve` |
| `sim connect` | ソルバーを起動し、セッションを開く | `docker start` |
| `sim exec` | ライブセッション内で Python スニペットを実行 | `docker exec` |
| `sim inspect` | ライブセッション状態を照会（`session.versions` 含む） | `docker inspect` |
| `sim ps` | アクティブなセッションとその profile を表示 | `docker ps` |
| `sim screenshot` | ソルバー GUI の PNG を取得 | — |
| `sim disconnect` | セッションを撤収 | `docker stop` |
| `sim run` | ワンショットスクリプト実行 | `docker run` |
| `sim lint` | スクリプトの事前静的チェック | `ruff check` |
| `sim logs` | 保存されたラン履歴を閲覧 | `docker logs` |

ホストに触るすべてのコマンド（`check`、`env`、`connect`、`exec`、`inspect`、`disconnect`）は `--host <ip>` を受け付け、ローカルマシンの代わりにリモートの `sim serve` に対して実行されます。

環境変数: クライアント用 `SIM_HOST`、`SIM_PORT`。ラン保存と profile env 用 `SIM_DIR`（デフォルト `.sim/`）。

### profile の選び方

普通は選ぶ必要はありません。`sim check <solver>` がインストール済みソルバーの対応 profile を教えてくれますし、`sim connect ... --auto-install` が初回使用時に自動で bootstrap します。エスケープハッチ：

- **profile を固定する：** `sim connect --solver fluent --profile pyfluent_0_37_legacy`
- **profile env を完全にスキップ（レガシー / テスト）：** `sim connect --solver fluent --inline`
- **上級者向けの単一 env インストール：** `pip install 'sim-cli[fluent-pyfluent-0-38]'` で SDK を直接現在の venv に入れます。`sim env` を介さない方法。同じマシンで Fluent のバージョンが 1 つしか要らないときに向きます。

完全な設計：[`docs/architecture/version-compat.md`](architecture/version-compat.md)

---

## 🆚 なぜスクリプトをそのまま走らせないのか？

| 撃ちっぱなしスクリプト | sim |
|---|---|
| 全体を書いて、走らせて、収束を祈る | 接続 → 実行 → 観察 → 次のステップを決定 |
| ステップ 2 のエラーがステップ 12 で露出 | 各ステップが次を送る前に検証される |
| エージェントはソルバー状態が見えない | 各アクションの間で `sim inspect` |
| 反復ごとにソルバー再起動 | 1 つの持続セッション、スニペットは好きなだけ |
| GUI が人間に不可視 | エンジニアが GUI を見て、エージェントが駆動 |
| 出力パースがプロジェクトごとに再発明 | `driver.parse_output()` が構造化フィールドを返す |

---

## 🧪 ソルバーレジストリ

ドライバーレジストリは**オープンで、意図的に成長する設計** ── 新しいバックエンドの追加は ~200 LOC の `DriverProtocol` 実装と `drivers/__init__.py` の 1 行の登録だけ。下記は現在 `main` に入っているスナップショットです：

| ドメイン | 今日動く例示バックエンド | セッション | ステータス |
|---|---|---|---|
| CFD | Ansys Fluent、OpenFOAM | 持続 / ワンショット | ✅ Working |
| マルチフィジックス | COMSOL Multiphysics | ワンショット | ✅ Working |
| 前処理 | BETA CAE ANSA | 持続 / ワンショット | ✅ Working (Phase 1) |
| 電子機器熱解析 | Simcenter Flotherm | ワンショット | ✅ Working (Phase A) |
| 数値 / スクリプト | MATLAB | ワンショット | ✅ Working (v0) |
| 電池モデリング | PyBaMM | ワンショット | ✅ Working |
| **+ あなたのソルバー** | PR をどうぞ ── [開発](#-開発) を参照 | — | 🛠 |

ソルバーごとのプロトコル、スニペット、デモワークフローは [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) にあります。これも**同様に成長するよう設計されており** ── 新しいバックエンドごとに 1 つの新しいエージェントスキルを追加します。

---

## 🛠 開発

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev]"

pytest -q                       # ユニットテスト（ソルバー不要）
pytest -q -m integration        # 統合テスト（ソルバー + sim serve が必要）
ruff check src/sim tests
```

新しいドライバーを追加したい？ `src/sim/drivers/<name>/driver.py` に `DriverProtocol` 実装を置き、`drivers/__init__.py` に登録するだけ。最小のリファレンスは `pybamm/driver.py`、完全な持続セッション例は `fluent/`。

---

## 📂 プロジェクト構成

```
src/sim/
  cli.py           Click アプリ、全サブコマンド
  server.py        FastAPI サーバー（sim serve）
  session.py       connect/exec/inspect 用 HTTP クライアント
  driver.py        DriverProtocol + 結果データクラス
  drivers/
    fluent/        参考例: 持続セッションドライバー
                   (driver.py + runtime.py + queries.py)
    pybamm/        参考例: 最小のワンショットドライバー
    …              その他 ── 登録済みバックエンドごとに 1 フォルダ
    __init__.py    DRIVERS レジストリ ── 新しいバックエンドをここに登録
tests/             ユニットテスト + fixtures + 実行スニペット
assets/            logo · banner · architecture (SVG)
docs/              翻訳済み README（de · ja · zh）
```

---

## 🔗 関連プロジェクト

- **[`sim-skills`](https://github.com/svd-ai-lab/sim-skills)** ── 各サポートソルバーのエージェントスキル、スニペット、デモワークフロー

---

## 📄 ライセンス

Apache-2.0 ── [LICENSE](../LICENSE) を参照。
