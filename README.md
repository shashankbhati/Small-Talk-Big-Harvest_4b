# Coffee Helpline: registration app

The smartphone side of a voice helpline for smallholder farmers, built by team **Small Talk, Big Harvest**
for the Hack-Nation x World Bank "Small AI for Development" hackathon (Challenge 04, Agriculture).

A family member registers the farm once in this app. After that the farmer calls the helpline from a
basic phone, describes the crop problem in Hindi, and hears a pre-written answer. The same answer then
appears in this app, so it can be read again later.

## What the app does

- **Register once:** phone number, farm location (GPS or village name), crops and field size, one
  question per screen, in Hindi with an English switch and a read-aloud button.
- **Show past calls:** the likely problem and the advice for each call, or "an officer will call you"
  when the helpline was not sure.
- **Work on a weak connection:** it installs as a PWA, opens offline after the first visit, keeps a
  registration on the phone until there is a signal, and keeps the last loaded advice readable offline.
- **Privacy:** location is rounded to about 1 km before it leaves the phone, there are no trackers or
  analytics, and "Delete my data" removes everything on the server and on the phone.

## How it connects to the helpline

The app has no database of its own. It talks to the helpline backend
([coffee-voice-advisor](https://github.com/shashankbhati/coffee-voice-advisor)):

| Call | Purpose |
|---|---|
| `POST /api/farmers` | register, returns a token kept on the phone |
| `GET /api/farmers/me/cases` | answers given on calls since registration |
| `PUT /api/farmers/me` | change details |
| `DELETE /api/farmers/me` | delete everything |

Settings are in [`src/lib/config.ts`](src/lib/config.ts): the backend address, the helpline number and
the team contact shown in the privacy policy. The backend address can be overridden at build time with
`VITE_API_BASE_URL` (in `.env.local`, or in the Vercel project settings).

## Deploying to Vercel

The build targets Cloudflare by default (Lovable). For Vercel, set the environment variable
`NITRO_PRESET=vercel` in the project, or build locally and upload the result:

```sh
NITRO_PRESET=vercel npm run build
vercel deploy --prebuilt --prod
```

On a phone, open the deployed address and choose "Add to Home screen" to install it.

## Limits

- There is no SMS code check: the app trusts the phone number that is typed in.
- The Hindi texts are drafts and need review by a native speaker.
- The place list is a short demo list.

## Development

Built with [Lovable](https://lovable.dev) (TanStack Start, React, Tailwind).

```sh
npm i
npm run dev
npm test
```
