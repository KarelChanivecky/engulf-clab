# Plugin instructions

- Keep plugin ID `engulf_clab.fortinet_operation_guard` and both executable-wrapper
  entry points stable.
- Resolve effective node kinds through `engulf-clab-lab-parser`; recognize only
  `fortinet_fortigate` and `fortinet_fortiproxy`.
- Preempt explicit `restart` and `deploy --reconfigure` calls during analysis.
  A plain deploy may inspect Docker only during preparation, after analyzers
  accept the call.
- Match running containers by Containerlab topology labels first, with the lab
  name as the fallback when no topology label is present.
- Do not mutate topology files, containers, or persistent state. Diagnostics
  must go through the callback-bound logger.
- Keep parser and schema ordering in package metadata, not on the plugin class.
