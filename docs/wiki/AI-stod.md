# AI-stöd

AI är avstängt från start.

En admin måste:

1. välja provider under `Settings`
2. spara nödvändiga nycklar eller URL:er
3. köra ett lyckat anslutningstest

Stödda providers:

- disabled
- OpenAI
- Claude
- Ollama

## Redaktion

Redaktion är på som standard. Appen maskar bland annat:

- personnummerliknande mönster
- e-post
- telefonnummer
- IBAN och kontonummer
- egna ord och fraser

Det är fortfarande ditt ansvar att avgöra vilka dokument som får skickas till extern AI. För strikt lokal drift, använd Ollama eller lämna AI avstängt.
