# Drittkomponenten und ihre Lizenzen

`lynx-mcp` selbst steht unter der **MIT-Lizenz** ([LICENSE](LICENSE), © 2026
ITAgnesmeyer). Dieses Dokument listet die Komponenten von Dritten, die dieses
Paket verwendet, mit den jeweiligen Lizenzverweisen.

Stand: 2026-11-25 — Versionen aus der aufgelösten Umgebung (`uv.lock`).

## Abhängigkeiten zur Laufzeit (Python-Pakete)

Direkte Abhängigkeit ist nur `mcp`; die übrigen Pakete werden transitiv
aufgelöst. Die vollständigen Lizenztexte liegen in den jeweiligen
Quell-/`dist-info`-Verzeichnissen und über die verlinkten Projekte.

| Paket | Version | Lizenz | Projekt / Lizenztext |
|---|---|---|---|
| `mcp` (Model Context Protocol SDK) | 2.3.0 | MIT | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) · [LICENSE](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) |
| `mcp-types` | 2.3.0 | MIT | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| `pydantic` | 2.14.4 | MIT | [pydantic/pydantic](https://github.com/pydantic/pydantic) · [LICENSE](https://github.com/pydantic/pydantic/blob/main/LICENSE) |
| `pydantic_core` | 2.50.5 | MIT | [pydantic/pydantic-core](https://github.com/pydantic/pydantic-core) |
| `annotated-types` | 0.8.0 | MIT | [annotated-types/annotated-types](https://github.com/annotated-types/annotated-types) |
| `typing_extensions` | 4.16.0 | PSF-2.0 | [python/typing_extensions](https://github.com/python/typing_extensions) · [LICENSE](https://github.com/python/typing_extensions/blob/main/LICENSE) |
| `typing-inspection` | 0.4.5 | MIT | [pydantic/typing-inspection](https://github.com/pydantic/typing-inspection) |
| `anyio` | 4.16.0 | MIT | [agronholm/anyio](https://github.com/agronholm/anyio) |
| `idna` | 3.20 | BSD-3-Clause | [kjd/idna](https://github.com/kjd/idna) · [LICENSE.md](https://github.com/kjd/idna/blob/master/LICENSE.md) |
| `httpx2` | 2.16.2 | BSD-3-Clause | [pydantic/httpx2](https://github.com/pydantic/httpx2) |
| `httpcore2` | 2.16.2 | BSD-3-Clause | [pydantic/httpx2](https://github.com/pydantic/httpx2) |
| `h11` | 0.16.0 | MIT | [python-hyper/h11](https://github.com/python-hyper/h11) |
| `uvicorn` | 0.54.0 | BSD-3-Clause | [Kludex/uvicorn](https://github.com/Kludex/uvicorn) |
| `click` | 8.5.1 | BSD-3-Clause | [pallets/click](https://github.com/pallets/click) · [LICENSE.txt](https://github.com/pallets/click/blob/main/LICENSE.txt) |
| `starlette` | 1.10.0 | BSD-3-Clause | [Kludex/starlette](https://github.com/Kludex/starlette) |
| `sse-starlette` | 3.7.1 | BSD-3-Clause | [sysid/sse-starlette](https://github.com/sysid/sse-starlette) |
| `python-multipart` | 0.0.34 | Apache-2.0 | [Kludex/python-multipart](https://github.com/Kludex/python-multipart) |
| `PyJWT` | 2.15.1 | MIT | [jpadilla/pyjwt](https://github.com/jpadilla/pyjwt) |
| `cryptography` | 50.0.2 | Apache-2.0 **oder** BSD-3-Clause (Wahl) | [pyca/cryptography](https://github.com/pyca/cryptography) · [LICENSE](https://github.com/pyca/cryptography/blob/main/LICENSE) |
| `cffi` | 2.1.1 | MIT-0 | [python-cffi/cffi](https://github.com/python-cffi/cffi) |
| `pycparser` | 3.12 | BSD-3-Clause | [eliben/pycparser](https://github.com/eliben/pycparser) |
| `jsonschema` | 4.26.0 | MIT | [python-jsonschema/jsonschema](https://github.com/python-jsonschema/jsonschema) |
| `jsonschema-specifications` | 2025.9.1 | MIT | [python-jsonschema/jsonschema-specifications](https://github.com/python-jsonschema/jsonschema-specifications) |
| `referencing` | 0.37.0 | MIT | [python-jsonschema/referencing](https://github.com/python-jsonschema/referencing) |
| `rpds-py` | 2026.9.1 | MIT | [crate-py/rpds](https://github.com/crate-py/rpds) |
| `attrs` | 26.1.0 | MIT (PSF-kompatibel) | [python-attrs/attrs](https://github.com/python-attrs/attrs) |
| `opentelemetry-api` | 1.45.2 | Apache-2.0 | [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) |
| `truststore` | 0.10.5 | MIT | [sethmlarson/truststore](https://github.com/sethmlarson/truststore) |
| `pywin32` (nur Windows) | 312 | PSF-lizenziert | [mhammond/pywin32](https://github.com/mhammond/pywin32) · [LICENSE](https://github.com/mhammond/pywin32/blob/main/LICENSE) |
| `colorama` (nur Windows) | 0.4.6 | BSD-3-Clause | [tartley/colorama](https://github.com/tartley/colorama) |

## Externe Software (nicht enthalten)

| Komponente | Lizenz | Anmerkung |
|---|---|---|
| [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE) | **AGPL-3.0** | **Nicht Bestandteil dieses Repositories.** `lynx-mcp` enthält keinen Code, keine Assets und keine Dokumentation von LYNX SHARE; es verbindet sich lediglich als TCP-Client mit einer laufenden Instanz über das dokumentierte `lynx-control/1`-Protokoll ([REMOTE_CONTROL.md](https://github.com/Ka1-S/LYNX-SHARE/blob/main/docs/REMOTE_CONTROL.md)). Die DAW ist ein eigenständiges, getrenntes Programm; für die Nutzung gilt die EULA/Lizenz von LYNX SHARE selbst. |
| Python-Laufzeit (CPython ≥ 3.10) | PSF | `lynx-mcp` nutzt nur die Standardbibliothek (`socket`, `hashlib`, `hmac`, `json`, …); deren Dokumentation unterliegt der PSF-Lizenz. |

## Entwicklungs- und Build-Werkzeuge (nicht mit ausgeliefert)

| Werkzeug | Version | Lizenz | Projekt |
|---|---|---|---|
| `pytest` | 9.2.0 | MIT | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| `pluggy` | 1.7.0 | MIT | [pytest-dev/pluggy](https://github.com/pytest-dev/pluggy) |
| `iniconfig` | 2.3.1 | MIT | [pytest-dev/iniconfig](https://github.com/pytest-dev/iniconfig) |
| `packaging` | 26.4 | Apache-2.0 **oder** BSD-2-Clause (Wahl) | [pypa/packaging](https://github.com/pypa/packaging) |
| `Pygments` | 2.21.0 | BSD-2-Clause | [pygments/pygments](https://github.com/pygments/pygments) |
| `hatchling` (Build-Backend) | aktuell | MIT | [pypa/hatch](https://github.com/pypa/hatch) |
| [`uv`](https://docs.astral.sh/uv/) (Start/Tooling) | aktuell | Apache-2.0 **oder** MIT (Wahl) | [astral-sh/uv](https://github.com/astral-sh/uv) |

## Hinweise

- **„Wahl“ (OR-Lizenzen):** Bei Dual-Lizenzen wie `Apache-2.0 OR BSD-3-Clause`
  darf der Nutzer eine der beiden Lizenzen wählen; hier wird die Komponente
  nach BSD-Konvention als OSI-konform genutzt.
- Die SPDX-Kurzbezeichner folgen der [SPDX License List](https://spdx.org/licenses/);
  vollständige Lizenztexte sind über die verlinkten Repositories bzw. in den
  `*.dist-info/licenses`-Verzeichnissen der installierten Pakete
  (`.venv/Lib/site-packages`) abrufbar.
- Trademarks (JUCE, VST, FL Studio u. a.) gehören ihren jeweiligen Eigentümern;
  Namen werden hier nur zur Beschreibung der Kompatibilität verwendet.
