<div align="center">

<img src="../assets/banner.svg" alt="sim — Mache jedes Engineering-Tool agent-nativ" width="820">

<br>

**Mache jedes Engineering-Tool agent-nativ.**

*Heutige CAD- und CAE-Software wurde für Ingenieure gebaut, die durch GUIs klicken.*
*Der Nutzer von morgen ist ein LLM-Agent — und er braucht einen Weg hinein.*

<p align="center">
  <a href="#-schnellstart"><img src="https://img.shields.io/badge/Schnellstart-2_Min-3b82f6?style=for-the-badge" alt="Schnellstart"></a>
  <a href="#-solver-registry"><img src="https://img.shields.io/badge/Solver-wachsende_Registry-22c55e?style=for-the-badge" alt="Wachsende Solver-Registry"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8b5cf6?style=for-the-badge" alt="Begleit-Skills"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/Lizenz-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click_8-blue" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/transport-HTTP%2FJSON-orange" alt="HTTP/JSON">
  <img src="https://img.shields.io/badge/status-alpha-f97316" alt="Status: alpha">
</p>

[English](../README.md) · **Deutsch** · [日本語](README.ja.md) · [中文](README.zh.md)

[Warum sim](#-warum-sim) · [Schnellstart](#-schnellstart) · [Demo](#-demo) · [Befehle](#-befehle) · [Solver](#-solver-registry) · [Skills](https://github.com/svd-ai-lab/sim-skills)

</div>

---

## 🤔 Warum sim?

LLM-Agenten wissen längst, wie man Simulationsskripte schreibt — die Trainingsdaten sind voll davon. Was ihnen fehlt, ist eine standardisierte Möglichkeit, **einen Solver zu starten, ihn schrittweise zu steuern und zwischen jedem Schritt zu beobachten**, was passiert ist, bevor sie den nächsten Zug entscheiden.

Heutige Optionen sind unzureichend:

- **Fire-and-forget-Skripte** — Der Agent schreibt 200 Zeilen, lässt das Ganze laufen, ein Fehler in Zeile 30 erscheint als Müll in Zeile 200, keine Introspektion, keine Recovery.
- **Eigenbau-Wrapper pro Solver** — Jedes Team baut denselben launch / exec / inspect / teardown-Zyklus in einer anderen Form neu.
- **Geschlossener Hersteller-Klebstoff** — Vendor-SDKs, die nicht komponieren, kein gemeinsames Vokabular haben und kein HTTP sprechen.

`sim` ist die fehlende Schicht:

- **Eine CLI**, ein HTTP-Protokoll, eine **wachsende Driver-Registry**, die CFD, Multiphysik, Thermik, Vorverarbeitung und mehr umfasst.
- **Persistente Sessions**, die der Agent zwischen jedem Schritt introspektiert.
- **Remote-by-default** — CLI-Client und der laufende Solver dürfen auf verschiedenen Maschinen leben (LAN, Tailscale, HPC-Head-Node).
- **Begleit-Agent-Skills**, die einem LLM beibringen, wie man jeden neuen Backend sicher bedient.

> So wie eine Container-Runtime standardisierte, wie Kubernetes mit Containern spricht, standardisiert **sim**, wie Agenten mit Engineering-Software sprechen.

---

## 🏛 Architektur

<div align="center">
  <img src="../assets/architecture.svg" alt="sim Architektur: CLI-Client per HTTP/JSON zu einem sim-serve FastAPI-Prozess, der eine echte Solver-Session hält" width="900">
</div>

Zwei Ausführungsmodi aus derselben CLI, beide mit demselben `DriverProtocol`:

| Modus | Befehl | Wann verwenden |
|---|---|---|
| **Persistente Session** | `sim serve` + `sim connect / exec / inspect` | Lange, zustandsbehaftete Workflows, die der Agent zwischen Schritten introspektiert |
| **One-shot** | `sim run script.py --solver X` | Komplette Skript-Jobs, die als nummerierter Run in `.sim/runs/` gespeichert werden sollen |

Vollständiges Driver-Protokoll, Server-Endpunkte und Execution-Pipeline siehe [CLAUDE.md](../CLAUDE.md).

---

## 🚀 Schnellstart

> **Namen auf einen Blick:** Repo `svd-ai-lab/sim-cli` · PyPI-Distribution `sim-cli-core` · CLI-Befehl `sim` · Import `import sim`. Ja, drei verschiedene Strings — der Repo-Name ist älter als der erste PyPI-Release; der Rest folgt Python-Paketierungs-Konvention.

```bash
# 1. Auf der Maschine mit dem Solver,
#    erst nur sim core installieren — noch keine SDK-Wahl:
uv pip install sim-cli-core

# 2. sim die Maschine ansehen lassen und das passende Profil wählen:
sim check <solver>
# → meldet erkannte Installs des Solvers und das Profil, zu dem sie auflösen

# 3. Dieses Profil-Env aufsetzen (legt .sim/envs/<profile>/ mit gepinntem
#    SDK an; alternativ in Schritt 5 --auto-install verwenden):
sim env install <profile>

# 4. Server starten (nur für netzwerkübergreifende Workflows nötig):
sim serve --host 0.0.0.0          # FastAPI auf :7600

# 5. Vom Agenten / Laptop / irgendwo im Netzwerk:
sim --host <server-ip> connect --solver <solver> --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← immer zuerst
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

Das ist die volle Schleife: **erkennen → bootstrappen → starten → steuern → beobachten → abbauen** — der Ingenieur kann optional die Solver-GUI in Echtzeit beobachten.

> **Warum der Bootstrap-Schritt?** Jede `(Solver, SDK, Driver, Skill)`-Kombination
> ist ein eigenes Kompatibilitäts-Universum — verschiedene Solver-Releases
> brauchen oft unterschiedliche SDK-Versionen, und diese SDK-Versionen
> koexistieren nicht immer in einem Python-env. sim behandelt jede
> Kombination als isoliertes "Profile-Env", damit mehrere Versionen ohne
> Abhängigkeitskonflikt auf derselben Maschine koexistieren können. Der
> Vertrag steht in
> [`docs/architecture/version-compat.md`](architecture/version-compat.md).

---

## 🎬 Demo

> 📺 **Frühe Vorschau:** [erster Walkthrough auf YouTube](https://www.youtube.com/watch?v=3Fg6Oph44Ik) — Rohschnitt, eine überarbeitete Aufnahme ist weiterhin willkommen (siehe unten).

> **Aufnahme in Arbeit.** Ein kurzer Terminal-Capture von `sim connect → exec → inspect → screenshot` gegen eine echte Solver-Session landet hier.
>
> Aufnahme beitragen? [`vhs`](https://github.com/charmbracelet/vhs) oder [`asciinema`](https://asciinema.org/) verwenden und einen PR auf `assets/demo.gif` öffnen.

---

## ✨ Features

### 🧠 Für Agenten gebaut
- **Persistente Sessions** überleben Snippets — der Solver wird mitten in einem Task nie neu gestartet
- **Schrittweise Introspektion** mit `sim inspect` zwischen jeder Aktion
- **Pre-flight `sim lint`** fängt fehlende Imports und nicht unterstützte APIs vor dem Start
- **Nummerierte Run-Historie** in `.sim/runs/` für One-shot-Jobs, durchsuchbar via `sim logs`

### 🔌 Solver-agnostisch
- **Ein Protokoll** (`DriverProtocol`) — jeder Driver ist ~200 LOC, registriert in `drivers/__init__.py`
- **Persistent + One-shot** aus derselben CLI — kein separater Client pro Modus
- **Offene Registry** — neue Solver landen kontinuierlich; CFD, Multiphysik, Thermik, Vorverarbeitung, Batteriemodelle alles im Scope
- **Begleit-Skills** in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills), damit ein LLM die Eigenheiten jedes neuen Backends sofort kennt

### 🌐 Remote-freundlich
- **HTTP/JSON-Transport** — läuft überall, wo `httpx` läuft
- **Client / Server-Trennung** — Agent auf Laptop, Solver auf HPC-Knoten, GUI auf Workstation
- **Tailscale-ready** — entworfen für Mesh-Deployments über Netzwerke hinweg

---

## ⚙️ Befehle

| Befehl | Was er tut | Analogie |
|---|---|---|
| `sim check <solver>` | Installationen erkennen + Profil auflösen | `docker info` |
| `sim env install <profile>` | Profile-Env aufsetzen (venv + gepinntes SDK) | `pyenv install` |
| `sim env list [--catalogue]` | Aufgesetzte Envs (oder den vollen Katalog) zeigen | `pyenv versions` |
| `sim env remove <profile>` | Profile-Env abbauen | `pyenv uninstall` |
| `sim serve` | HTTP-Server starten (für maschinenübergreifenden Einsatz) | `ollama serve` |
| `sim connect` | Solver starten, Session öffnen | `docker start` |
| `sim exec` | Python-Snippet in der Live-Session laufen lassen | `docker exec` |
| `sim inspect` | Live-Session-Status abfragen (inkl. `session.versions`) | `docker inspect` |
| `sim ps` | Aktive Session und ihr Profil zeigen | `docker ps` |
| `sim screenshot` | PNG der Solver-GUI erfassen | — |
| `sim disconnect` | Session abbauen | `docker stop` |
| `sim run` | One-shot Skript-Ausführung | `docker run` |
| `sim lint` | Pre-flight Static-Check für ein Skript | `ruff check` |
| `sim logs` | Run-Historie durchstöbern | `docker logs` |

Jeder Befehl, der einen Host berührt (`check`, `env`, `connect`, `exec`, `inspect`, `disconnect`), akzeptiert `--host <ip>` und läuft dann gegen ein Remote `sim serve` statt gegen die lokale Maschine.

Umgebungsvariablen: `SIM_HOST`, `SIM_PORT` für den Client; `SIM_DIR` (Standard `.sim/`) für Run-Storage und Profile-Envs.

### Profil wählen

Meistens muss man nichts wählen. `sim check <solver>` sagt dir, zu welchem Profil dein installierter Solver auflöst, und `sim connect ... --auto-install` setzt es beim ersten Gebrauch automatisch auf. Die Notausgänge:

- **Profil festsetzen:** `sim connect --solver <solver> --profile <profile>`
- **Profil-Env überspringen (Legacy / Tests):** `sim connect --solver <solver> --inline`
- **Power-User Single-Env-Install:** das passende Plugin-Paket direkt in die aktuelle venv installieren (z. B. `pip install <plugin-package>`). Überspringt `sim env`; sinnvoll, wenn du auf dieser Maschine nur eine Solver-Version brauchst.

Vollständiges Design: [`docs/architecture/version-compat.md`](architecture/version-compat.md).

---

## 🆚 Warum nicht einfach Skripte laufen lassen?

| Fire-and-forget-Skript | sim |
|---|---|
| Komplettes Skript schreiben, laufen lassen, Konvergenz hoffen | Connect → execute → observe → nächsten Schritt entscheiden |
| Fehler in Schritt 2 zeigt sich erst in Schritt 12 | Jeder Schritt verifiziert, bevor der nächste gesendet wird |
| Agent sieht keinen Solver-Zustand | `sim inspect` zwischen jeder Aktion |
| Solver startet bei jeder Iteration neu | Eine persistente Session, Snippets nach Belieben |
| GUI für den Menschen unsichtbar | Ingenieur beobachtet die GUI, während der Agent steuert |
| Output-Parsing pro Projekt neu erfunden | `driver.parse_output()` liefert strukturierte Felder |

---

## 🧪 Solver Registry

Die Driver-Registry ist **offen und absichtlich wachsend** — ein neuer Backend ist eine ~200 LOC `DriverProtocol`-Implementierung plus eine Zeile in `drivers/__init__.py`, oder ein Out-of-tree-Plugin-Paket, das über die `sim.drivers`-Entry-point-Gruppe registriert wird.

Die mitgelieferte Abdeckung umfasst CFD, Multiphysik, Elektronik-Thermik, implizite und explizite strukturelle FEA, Vor- und Nachverarbeitung, Mesh-Generierung, Embodied-AI / GPU-Physik, Molekulardynamik, Optimierung / MDAO, Batteriemodellierung, thermodynamische Stoffdaten, Energienetze und HF-Simulation sowie ereignisdiskrete Modellierung. Konkrete Solver werden entweder über die eingebaute Registry oder über Out-of-tree-Plugin-Pakete erreicht — siehe [`sim-plugin-cantera`](https://github.com/svd-ai-lab/sim-plugin-cantera) als Referenz-Plugin.

Per-Solver-Protokolle, Snippets und Demo-Workflows leben in [`sim-skills`](https://github.com/svd-ai-lab/sim-skills), das **ebenfalls so entworfen ist, dass es mitwächst** — ein neuer Agent-Skill pro neuem Backend.

---

## 🛠 Entwicklung

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev]"

pytest -q                       # Unit-Tests (kein Solver nötig)
pytest -q -m integration        # Integrationstests (Solver + sim serve nötig)
ruff check src/sim tests
```

Neuen Driver hinzufügen? Eine `DriverProtocol`-Implementierung im Tree ablegen oder als Out-of-Tree-Plugin über die `sim.drivers`-Entry-Point-Gruppe registrieren. Kleinste In-Tree-Referenz: `pybamm/driver.py`. Plugin-Referenz (Driver + Skill-Bundle): [`sim-plugin-cantera`](https://github.com/svd-ai-lab/sim-plugin-cantera).

---

## 📂 Projektstruktur

```
src/sim/
  cli.py           Click-App, alle Subcommands
  server.py        FastAPI-Server (sim serve)
  session.py       HTTP-Client für connect/exec/inspect
  driver.py        DriverProtocol + Result-Dataclasses
  drivers/
    pybamm/        Referenzbeispiel: kleinster One-shot-Driver
    …              und mehr — ein Ordner pro registriertem Built-in
    __init__.py    DRIVERS-Registry — neue In-Tree-Backends hier registrieren;
                   Out-of-Tree-Plugins werden zur Laufzeit über `sim.drivers`
                   Entry-Points entdeckt
tests/             Unit-Tests + Fixtures + Execution-Snippets
assets/            logo · banner · architecture (SVG)
docs/              Übersetzte READMEs (de · ja · zh)
```

---

## 🔗 Verwandte Projekte

- **[`sim-skills`](https://github.com/svd-ai-lab/sim-skills)** — Agent-Skills, Snippets und Demo-Workflows pro Backend

---

## 📄 Lizenz

Apache-2.0 — siehe [LICENSE](../LICENSE).
