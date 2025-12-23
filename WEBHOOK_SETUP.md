# Configurazione Webhook Emby per Aggiornamenti in Tempo Reale

## Vantaggi dei Webhook

**Prima (Polling ogni 5 secondi):**
- 12 richieste HTTP al minuto per server
- Latenza fino a 5 secondi per vedere nuovi stream
- Carico continuo sul server Emby

**Dopo (Webhook):**
- 0 richieste in idle
- Latenza < 100ms per aggiornamenti
- Carico server quasi zero
- Aggiornamenti istantanei

## Configurazione Emby

### 1. Accedi alle Impostazioni Webhook

1. Apri Emby Server
2. Vai su **Dashboard** > **Server** > **Webhooks**
3. Clicca su **Add Webhook** (Aggiungi Webhook)

### 2. Configura il Webhook

**URL Webhook:**
```
http://tuo-server:porta/webhook/emby
```

Esempio: `http://192.168.1.100:5000/webhook/emby`

**Eventi da Monitorare:**
Seleziona questi eventi:
- ✅ **Playback Started** (playback.start)
- ✅ **Playback Stopped** (playback.stop)
- ✅ **Playback Paused** (playback.pause)
- ✅ **Playback Unpaused** (playback.unpause)

**Filtri Utente/Dispositivo:**
Lascia vuoto per monitorare tutti gli utenti e dispositivi.

### 3. Sicurezza Opzionale

Per proteggere l'endpoint webhook da accessi non autorizzati:

**Imposta la variabile d'ambiente:**
```bash
export WEBHOOK_SECRET="tuo-segreto-sicuro-qui"
```

**Aggiungi Header Personalizzato in Emby:**
- Nome: `X-Webhook-Secret`
- Valore: `tuo-segreto-sicuro-qui`

⚠️ **Nota**: Se non imposti `WEBHOOK_SECRET`, il webhook accetta tutte le richieste (nessuna autenticazione).

**Whitelist IP (opzionale):**
```bash
export WEBHOOK_IP_WHITELIST="1.2.3.4,5.6.7.8"
```
Se impostata, solo gli IP presenti possono inviare eventi.

### 4. Test

1. Salva la configurazione webhook in Emby
2. Avvia la riproduzione di un file
3. Controlla i log del server:

```bash
tail -f logs/app.log
```

Dovresti vedere:
```
[WEBHOOK] Ricevuto evento: playback.start da server: NomeServer (server-id)
[WEBHOOK] Stream iniziato: session-id-123
```

### 5. Verifica Funzionamento

1. Apri **Emby Toolkit** nella dashboard
2. Avvia la riproduzione su Emby
3. Gli **Stream Attivi** dovrebbero aggiornarsi **istantaneamente** (< 1 secondo)

## Risoluzione Problemi

### Webhook non riceve eventi

**Verifica URL raggiungibile:**
```bash
curl -X POST http://tuo-server:porta/webhook/emby \
  -H "Content-Type: application/json" \
  -d '{"Event":"test"}'
```

Dovrebbe rispondere: `{"success":true}`

**Controlla firewall:**
- Emby deve poter raggiungere il server webhook
- Se webhook e Emby sono su macchine diverse, apri la porta

**Controlla log Emby:**
Dashboard > Logs > Webhook - verifica errori di connessione

### Stream non si aggiornano

**Controlla mapping server:**
Il webhook cerca di mappare il server Emby alla configurazione locale usando:
1. Server ID Emby (`emby_server_id` nel config)
2. Nome server (`name` nel config)
3. Fallback: primo server abilitato se è l'unico

**Soluzione**: Aggiungi `emby_server_id` nel config dei server:
```json
{
  "EMBY": {
    "SERVERS": [
      {
        "id": "server-1",
        "name": "Emby Casa",
        "emby_server_id": "xxx-yyy-zzz",  // ← Aggiungi questo
        "url": "http://emby:8096",
        "api_key": "..."
      }
    ]
  }
}
```

Per trovare `emby_server_id`:
- Dashboard Emby > Server > About

### Secret non funziona

Se vedi `[WEBHOOK] Secret non valido, rifiuto richiesta`:

1. Verifica variabile d'ambiente impostata:
   ```bash
   echo $WEBHOOK_SECRET
   ```

2. Verifica header in Emby sia esattamente: `X-Webhook-Secret`

3. Riavvia l'app dopo aver impostato la variabile

## Fallback Automatico

Se webhook non è configurato o fallisce:
- Il sistema fa **fallback automatico** al polling API ogni 5 secondi
- Gli stream continuano a funzionare normalmente
- Nessuna perdita di dati, solo latenza maggiore

## Performance

**Con webhook attivi:**
- Latenza aggiornamenti stream: < 100ms
- Richieste HTTP a Emby: ~2-3 al minuto (solo per tasks/status)
- Carico CPU: minimo
- Banda: ~1 KB al minuto

**Senza webhook (fallback):**
- Latenza aggiornamenti stream: fino a 5 secondi
- Richieste HTTP a Emby: ~12-15 al minuto
- Carico CPU: leggero
- Banda: ~5-10 KB al minuto
