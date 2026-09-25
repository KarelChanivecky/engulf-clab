# Agent instructions

- Keep plugin ID `engulf_clab.vrnetlab_fortigate_license_injector` stable.
- Consume only the typed registered-license selection context and the shared
  topology session; use the selected lab-local copy, never the pool source.
- Mutate only deploy/redeploy `fortinet_fortigate` node binds and mount the
  selected license read-only at `/tftpboot/appliance.lic`.
- Validate the file and reject a conflicting destination before recording any
  topology mutation. Never log or expose license paths or contents.
- Preserve package-declared ordering after license selection and PKI bind
  generation, and before the topology writer. Keep the feature opt-in through
  the license-pool plugin.
- Do not acquire licenses, copy files, issue FortiOS commands, or own cleanup.
