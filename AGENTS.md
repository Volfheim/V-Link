# Project Instructions

## GitHub Releases

- Use `V-Link vX.Y.Z` as the release title and retain `vX.Y.Z` for the Git tag.
- Write equivalent English and Russian release notes. Start with a short English summary immediately followed by its Russian translation: the current in-app updater displays only the first 800 characters after basic Markdown cleanup. Put critical upgrade instructions in this opening when needed.
- Keep notes concise and focused on user-visible changes. Use simple headings and bullets that remain readable as plain text. Add sections only when they have relevant content; do not put internal test reports, build-process details or unverified claims in release prose.
- Identify the actual downloadable asset and its requirements, and link to a meaningful changelog range when available. Preserve historical tags and assets; disclose source-history or build-provenance limitations instead of inventing changes or silently replacing files.
- V-Link also delivers updates through its in-app updater. Preserve the `V-Link.exe` asset name unless updater compatibility has been addressed explicitly.

## Public documentation

- Keep the English `README.md` and Russian `README.ru.md` equivalent in features, setup and material limitations, with reciprocal language links.
- Show the real application UI. Screenshots may use clearly labeled example data, but must not imply measured transfer speed, completed real transfers or tested network compatibility without evidence.
- Distinguish desktop file encryption, mobile HTTP/WebDAV, clipboard sync and relay behavior. Document privacy-relevant defaults and describe session tokens according to their actual lifetime.
