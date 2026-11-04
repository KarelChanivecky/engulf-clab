# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, the schema, completion, and command code as
  one contract.
- Keep packet capture bound to a verified running Containerlab node and the
  declared direct link between the selected node pair.
- Treat the tcpdump argument allowlist as a security boundary. Add a flag only
  after checking its file, process, privilege, and interface effects.
- Do not invoke a shell, mount the Docker socket, modify a lab node, or declare
  an elevated eclab goal.
- Keep the helper transient and constrain its capabilities to `NET_RAW`.
- For `--wireshark`, use a temporary extcap interface so Wireshark's Stop and
  Restart controls own the capture lifecycle. Forward extcap stop signals to
  the Docker helper and wait for its container cleanup. Do not accept
  caller-supplied Wireshark arguments or install a persistent helper.
- Declare `wireshark` and `dumpcap` as option-level host tools on `--wireshark`;
  do not make them command-wide requirements.
- Run before the Containerlab provider's `sudoless` preemption and return
  without preempting that command. Add the user only to an existing
  `wireshark` or `packetcapture` group when `dumpcap` is root-owned, not
  group/world-writable, and already group-executable. Never change `dumpcap`
  ownership, mode, SUID, or capabilities.
- Keep the extcap capture plan in a private temporary directory, emit only
  extcap protocol output on stdout, and validate Wireshark's optional capture
  filter through the tcpdump allowlist. Drain helper stderr so ordinary Docker
  pull progress and tcpdump status lines do not become extcap pipe errors;
  forward bounded diagnostics only when capture fails.
- Keep the meta-package dependency and README catalog synchronized with this
  distribution.
- Run bytecode compilation and package metadata validation after source or
  packaging changes; integration captures require an operator's running lab and
  Docker daemon.
