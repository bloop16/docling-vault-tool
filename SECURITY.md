# Sicherheitshinweise / Security Policy

## Unterstützte Versionen

| Version | Unterstützt |
|---|---|
| 1.x | ✅ |
| < 1.0 | ❌ |

## Schwachstellen melden

Bitte Sicherheitsprobleme **nicht** als öffentliches Issue melden, sondern
über GitHub „Private vulnerability reporting" im Repository
(`Security → Report a vulnerability`). Rückmeldung in der Regel innerhalb
weniger Tage.

## Wichtige Betriebshinweise

- **Das Dashboard hat keine eingebaute Authentifizierung.** Standardmäßig
  nur auf `localhost` betreiben. Für Zugriff übers Netzwerk (Headless-
  Server, Docker) einen Reverse-Proxy mit Basic-Auth und TLS davorschalten
  — niemals direkt ins Internet exponieren. Beispiel (Caddy):

  ```caddyfile
  doc2vault.example.internal {
      basic_auth {
          nutzer $2a$14$...   # caddy hash-password
      }
      reverse_proxy localhost:8501
  }
  ```

  Beispiel (nginx): `auth_basic` + `proxy_pass http://localhost:8501;`
  inklusive WebSocket-Headern (`Upgrade`/`Connection`).

- **`--on-success delete` löscht Originaldateien** nach erfolgreicher
  Konvertierung. Vor dem ersten Lauf mit dieser Option ein Backup anlegen
  oder zunächst `archive` verwenden.

- **ZIP-Uploads** werden gegen Zip-Slip und Zip-Bombs geprüft
  (Pfad-Validierung, Limits für Eintragszahl, Gesamtgröße und
  Kompressionsrate) — die Limits stehen in `file_transfer.py`.

- **Ollama-Anbindung**: doc2vault sendet Notizinhalte zum konfigurierten
  Ollama-Server (`DOC2VAULT_OLLAMA_URL`). Bei sensiblen Daten nur lokale
  bzw. vertrauenswürdige Server verwenden.
