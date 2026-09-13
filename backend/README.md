# WeatherGPT Simple Backend

A single-file FastAPI backend for the SIH prototype.

## Features
- Gemini conversational weather assistant
- Open-Meteo current weather
- Up to 16-day forecast
- Threshold-based weather alerts
- JSON database
- JWT authentication
- Saved locations
- User profile
- User preferences
- Chat history

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Set these environment variables:

```text
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite
JWT_SECRET=...
```

Then open `/docs`.

The Gemini REST call follows Google's current `generateContent` API and
uses the `x-goog-api-key` header. Open-Meteo supplies geocoding and weather
forecast data.
