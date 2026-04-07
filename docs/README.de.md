# sim

> Einheitliche CLI für LLM-Agenten zur Steuerung von CAE-Simulationssoftware.

[English](../README.md) | **[Deutsch](#sim)** | [日本語](README.ja.md) | [中文](README.zh.md)

## Was es macht

LLM-Agenten können bereits Simulationsskripte schreiben (PyFluent, MATLAB usw.). Aber es gibt keine Standardmethode, um **schrittweise auszuführen, den Zustand zu beobachten und zu reagieren** — was bei langen, zustandsbehafteten und teuren Simulationen entscheidend ist.

sim ist die fehlende Laufzeitschicht. Wie `ollama` für LLMs, aber für CAE-Solver.

## Architektur

```
Mac / Agent                              Win / Server
┌──────────────┐   HTTP/Tailscale   ┌──────────────────┐
│  sim CLI     │ ────────────────>  │  sim serve       │
│  (Client)    │ <────────────────  │  (FastAPI)       │
└──────────────┘      JSON          │       │          │
                                    │  ┌────▼────────┐ │
                                    │  │ Fluent GUI   │ │
                                    │  │ (Ingenieur   │ │
                                    │  │  beobachtet) │ │
                                    │  └─────────────┘ │
                                    └──────────────────┘
```

## Schnellstart

```bash
# Auf dem Rechner mit Fluent (z.B. win1):
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"
sim serve --host 0.0.0.0

# Von überall im Netzwerk:
sim --host 100.90.110.79 connect --solver fluent --mode solver --ui-mode gui
sim --host 100.90.110.79 exec "solver.settings.mesh.check()"
sim --host 100.90.110.79 inspect session.summary
sim --host 100.90.110.79 disconnect
```

## Befehle

| Befehl | Funktion | Analogie |
|---|---|---|
| `sim serve` | HTTP-Server starten, Solver-Sitzungen halten | `ollama serve` |
| `sim connect` | Solver starten, Sitzung öffnen | `docker start` |
| `sim exec` | Code-Snippet in laufender Sitzung ausführen | `docker exec` |
| `sim inspect` | Live-Sitzungszustand abfragen | `docker inspect` |
| `sim ps` | Aktive Sitzungen auflisten | `docker ps` |
| `sim disconnect` | Sitzung beenden | `docker stop` |
| `sim run` | Einmalige Skriptausführung | `docker run` |
| `sim check` | Solver-Verfügbarkeit prüfen | `docker info` |
| `sim lint` | Skript vor Ausführung validieren | `ruff check` |
| `sim logs` | Ausführungsverlauf durchsuchen | `docker logs` |

## Warum nicht einfach Skripte ausführen?

| Traditionell (Fire-and-Forget) | sim (Schritt-für-Schritt-Kontrolle) |
|---|---|
| Ganzes Skript schreiben, ausführen, hoffen | Verbinden → Ausführen → Beobachten → Nächsten Schritt entscheiden |
| Fehler in Schritt 2 stürzt in Schritt 12 ab | Jeder Schritt wird vor dem Fortfahren überprüft |
| Agent kann Solver-Zustand nicht sehen | `sim inspect` zwischen jeder Aktion |
| Fluent bei jedem Lauf neu starten | Persistente Sitzung über Snippets hinweg |
| Keine GUI-Sichtbarkeit | Ingenieur beobachtet GUI, während Agent steuert |

## Unterstützte Solver

| Solver | Status | Backend |
|---|---|---|
| Ansys Fluent | Funktionsfähig | PyFluent (ansys-fluent-core) |
| PyBaMM | Grundlegend | Direktes Python |
| COMSOL | Geplant | MPh |
| OpenFOAM | Geplant | — |

## Lizenz

Apache-2.0
