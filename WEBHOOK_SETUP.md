# Configurazione Webhook Emby (Avanzata)

Questa guida spiega come configurare i webhook Emby per aggiornamenti in tempo reale degli stream e delle dashboard.

## Perche usare i webhook
Senza webhook, OctoHub usa un polling periodico (`STREAMS_REFRESH_SECONDS`).
Con webhook:
- aggiornamenti quasi immediati
- meno richieste verso Emby
- stato stream piu affidabile

## Prerequisiti
- OctoHub raggiungibile da Emby (LAN o Internet).
- URL pubblico o IP/porta locali validi.
- Se usi HTTPS, certificato valido consigliato.

## 1) Crea il webhook su Emby
1. Emby Server > Dashboard > Server > Webhooks
2. Add Webhook

URL consigliato:
- Produzione con HTTPS: `https://tuo-dominio/webhook/emby`
- LAN: `http://IP_OCTOHUB:PORTA/webhook/emby`

Eventi da abilitare:
- `Playback Started` (playback.start)
- `Playback Stopped` (playback.stop)
- `Playback Paused` (playback.pause)
- `Playback Unpaused` (playback.unpause)

## 2) Sicurezza (consigliata)
### Secret header
In `.env`:
```env
WEBHOOK_SECRET=segreto-lungo-e-unico
```

In Emby aggiungi header personalizzato:
- Nome: `X-Webhook-Secret`
- Valore: lo stesso di `WEBHOOK_SECRET`

### IP whitelist (opzionale)
```env
WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8
```

## 3) Mappatura server Emby
OctoHub abbina gli eventi Emby ai server configurati in `config.json` usando:
1) `emby_server_id` (se presente)
2) `name` (fallback)
3) se c'e un solo server abilitato, usa quello

Esempio:
```json
{
  "EMBY": {
    "SERVERS": [
      {
        "id": "server-1",
        "name": "Emby Casa",
        "emby_server_id": "xxx-yyy-zzz",
        "url": "http://emby:8096",
        "api_key": "API_KEY_EMBY",
        "enabled": true
      }
    ]
  }
}
```

Per trovare `emby_server_id`:
- Emby Server > Dashboard > Server > About

## 4) Test rapido
```bash
curl -X POST https://tuo-dominio/webhook/emby \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: segreto-lungo-e-unico" \
  -d '{"Event":"playback.start","Server":{"Name":"Emby Casa","Id":"xxx-yyy-zzz"},"Session":{"Id":"test"}}'
```

Risposta attesa:
```json
{"success": true}
```

## 5) Troubleshooting
- **401 Unauthorized**: `WEBHOOK_SECRET` non combacia.
- **403 Forbidden**: IP non in `WEBHOOK_IP_WHITELIST`.
- **200 ma nessun aggiornamento**: verifica `emby_server_id` o `name` nel config.
- **SSL self-signed**: se Emby rifiuta, usa HTTP in LAN o certificato valido.
- **Reverse proxy**: assicurati che `/webhook/emby` sia inoltrato correttamente.

## Fallback automatico
Se i webhook non arrivano, OctoHub usa il polling (intervallo da `STREAMS_REFRESH_SECONDS`).
