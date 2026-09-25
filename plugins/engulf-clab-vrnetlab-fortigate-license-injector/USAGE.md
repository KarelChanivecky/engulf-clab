# FortiGate vrnetlab license injection

## Installation and activation

Install `engulf-clab-vrnetlab-fortigate-license-injector`,
`engulf-clab-license-pool`, and `engulf-clab-pki` in the Python environment
that runs `eclab`. The PKI dependency keeps bind preparation ordered when a lab
also selects PKI. The feature activates only when the license-pool plugin selects a file for a node
whose resolved Containerlab kind is exactly `fortinet_fortigate`. No topology
control or product-prefix-specific environment variable is added. Editions use
the same `ECLAB_*` license-pool controls documented by that package.

Register a pool with the supported command and request its allocation in
Containerlab YAML:

```bash
eclab init-license-pool ./licenses --kind fortinet_fortigate
```

```yaml
topology:
  nodes:
    fortigate:
      kind: fortinet_fortigate
      image: vrnetlab/fortinet_fortigateb:8.0.0
      license: ECLAB_AUTO_LICENSE
```

The example pool path is local operator input and should not be committed with
license files. See Containerlab's upstream
[`schemas/clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json)
for the base topology syntax and the license-pool package's `USAGE.md` for
`license`, node-specific selection, command-line answers, and environment
controls. `eclab --help` reports the active installed feature inventory.

## Deployment and lifecycle

After the pool plugin allocates a real registered license, it copies that file
into workspace state and updates the derived deployment topology. This plugin
adds a read-only bind mount to `/tftpboot/appliance.lic`, which is the path the
FortiGate vrnetlab image's startup process serves to FortiOS. Containerlab then
starts the VM and vrnetlab can install the license during boot.

The adapter also runs for single-source `redeploy`. It does nothing on other
commands, when no license was selected, or for a different effective node kind.
An existing mount at `/tftpboot/appliance.lic` must be the same selected file
and read-only; a conflicting mount makes preparation fail before Containerlab
runs. PKI and other inherited binds are retained.

License claims and generated copies remain owned by
`engulf-clab-license-pool`. A failed deploy rolls back a newly created claim and
copy; a successful destroy releases them according to that package's lifecycle.
The injector keeps no independent state and has no cleanup command. Do not
manually remove a claimed copy while a lab is running.

## Security and state

Only a path is added to the derived topology. The license bytes are not read by
this plugin, embedded in an archive, logged, or included in reports. The
container sees the selected workspace copy through a read-only mount. Registry
state, allocation locks, and copy permissions are managed by the license-pool
plugin in the usual user and workspace state directories.

The source topology remains unchanged; the topology writer removes its
temporary derived file after destroy. Freeze archives retain the authored
license selection and are expected to allocate a valid recipient license from
that recipient's registered pool at deploy time.

## Troubleshooting

- If FortiOS remains unlicensed, confirm that `license` requests a registered
  pool allocation, the pool is registered for `fortinet_fortigate`, and a valid
  free license is available. The allocator's normal lock and claim rules still
  apply.
- If preparation reports an unavailable selected copy, let the license-pool
  plugin recreate it through a normal deploy attempt; do not replace it with a
  manually mounted pool source.
- If preparation reports a conflicting mount, remove the authored mount at
  `/tftpboot/appliance.lic` and allow this adapter to add the selected file.
- If the injector is absent from `eclab --help`, install it into the launcher's
  environment alongside `engulf-clab-license-pool` and `engulf-clab-pki`, then
  check plugin discovery.
