# Plugin Instructions

- Keep plugin ID `engulf_clab.sticky_ip`, priority `-90`, and parser-before / writer-after package ordering stable.
- Treat `deploy` and single-source `redeploy` as deployment commands. Keep analysis side-effect free and perform Docker, route, probe, lease, state, and topology work only in preparation.
- Use only RFC1918 IPv4 and ULA IPv6 pools. A logical unit is `/24` or `/120` and exposes offsets 2 through 129 as 128 stable node slots.
- Persist only allocation metadata in user state. Hold the `sticky-ip-registry` lease around host inspection and claims, and keep state transactions short.
- Unwind this attempt in an inner `BaseException` handler and unwind completed preparation through `prepare_failed()`. Never release a previous successful deployment's claim.
- Keep failed started deployments reserved. Release claims only after successful destroy without `--keep-mgmt-net`.
- Never edit source topology YAML. Add `mgmt` subnet/network fields and per-node fixed addresses through the shared topology session.
- Select management-attached nodes through the shared EffectiveNode resolver,
  including inherited kind/group selectors and network-mode.
- Keep CLI help, `PluginSchema`, `USAGE.md`, state validation, availability checks, and tests synchronized.
- Mock Docker, route, traceroute, and Containerlab operations in tests; never mutate host networking.
