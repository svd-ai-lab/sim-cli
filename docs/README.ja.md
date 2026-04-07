# sim

> LLMエージェントがCAEシミュレーションソフトウェアを制御するための統合CLI。

[English](../README.md) | [Deutsch](README.de.md) | **[日本語](#sim)** | [中文](README.zh.md)

## 概要

LLMエージェントはトレーニングデータからシミュレーションスクリプト（PyFluent、MATLABなど）の書き方を既に知っています。しかし、**ステップごとに実行し、状態を観察し、次のアクションを判断する**ための標準的な方法がありません。シミュレーションは長時間で、状態を持ち、コストがかかるため、これは重要です。

ionは欠けていたランタイム層です。LLM向けの`ollama`のように、CAEソルバー向けのツールです。

## アーキテクチャ

```
Mac / エージェント                        Win / サーバー
┌──────────────┐   HTTP/Tailscale   ┌──────────────────┐
│  sim CLI     │ ────────────────>  │  sim serve       │
│  (クライアント) │ <────────────────  │  (FastAPI)       │
└──────────────┘      JSON          │       │          │
                                    │  ┌────▼────────┐ │
                                    │  │ Fluent GUI   │ │
                                    │  │ (エンジニアが │ │
                                    │  │  監視)       │ │
                                    │  └─────────────┘ │
                                    └──────────────────┘
```

## クイックスタート

```bash
# Fluentが��ンストールされたマシンで（例：win1）：
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"
sim serve --host 0.0.0.0

# ネットワーク上のどこからでも：
sim --host 100.90.110.79 connect --solver fluent --mode solver --ui-mode gui
sim --host 100.90.110.79 exec "solver.settings.mesh.check()"
sim --host 100.90.110.79 inspect session.summary
sim --host 100.90.110.79 disconnect
```

## コマンド

| コマンド | 機能 | 類似ツール |
|---|---|---|
| `sim serve` | HTTPサーバーを起動、ソルバーセッションを保持 | `ollama serve` |
| `sim connect` | ソルバーを起動、セッションを開く | `docker start` |
| `sim exec` | ライブセッシ��ンでコードスニペットを実行 | `docker exec` |
| `sim inspect` | ライブセッション状態を照会 | `docker inspect` |
| `sim ps` | アクティブセッションを一覧表示 | `docker ps` |
| `sim disconnect` | セッションを終了 | `docker stop` |
| `sim run` | ワンショットスクリプト実行 | `docker run` |
| `sim check` | ソルバーの利用可能性を確認 | `docker info` |
| `sim lint` | 実行前にスクリプトを検証 | `ruff check` |
| `sim logs` | 実行履歴を閲覧 | `docker logs` |

## なぜスクリプトをそのまま実行しないのか？

| 従来型（実行して祈る） | sim（ステップごとの制御） |
|---|---|
| スクリプト全体を書いて実行 | 接続 → 実行 → 観察 → 次のステップを判断 |
| ステップ2のエラーがステップ12でクラッシュ | 各ステップを進行前に検証 |
| エージェントがソルバー状態を見られない | 各アクション間で`sim inspect` |
| 毎回Fluentを再起動 | スニペット間で永続的セッション |
| GUIが見えない | エージェントが操作中、エンジニアがGUIを監視 |

## 対応ソルバー

| ソルバー | 状態 | バックエンド |
|---|---|---|
| Ansys Fluent | 動作中 | PyFluent (ansys-fluent-core) |
| PyBaMM | 基本対応 | Python直接実行 |
| COMSOL | 予定 | MPh |
| OpenFOAM | 予定 | — |

## ライセンス

Apache-2.0
