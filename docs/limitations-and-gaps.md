# Limitations and Known Gaps

- The frontend is a static SPA served by FastAPI rather than a compiled React build.
- The workshop depends on preview Azure AI Search features for native answer synthesis and image serving, so API behavior can still change across preview versions.
- The Foundry Agent Service + MCP hop is not wired into the runtime yet.
- Local PDF and Office parsing remain intentionally limited outside workshop strict mode; the workshop path itself expects Azure parsers instead of local fallbacks.
- Page-range splitting, throughput throttling, and OCR-only-on-selected-pages are scaffolded as architectural seams, not fully automated execution policies.
- Content Understanding output mapping can differ by analyzer design and may require environment-specific tuning in the optional advanced lab.
