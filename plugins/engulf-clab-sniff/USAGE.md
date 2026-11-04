# Host-side link capture

Install `engulf-clab-sniff` beside `engulf-clab`, or install it through
`engulf-clab-all-plugins`. The active launcher adds this command:

```text
eclab sniff [--topology FILE] NODE1 NODE2 [--interface IFACE] [--write FILE | --wireshark] [--] [tcpdump options] [BPF filter]
```

For another installed edition, use that edition's launcher in place of
`eclab`. The plugin is discovered from its installed package entry points; it
does not need a topology extension or a separate activation file.
The plugin defines no environment variables.

## Selecting the capture

Without `--topology` or `-t`, the current directory must contain exactly one
Containerlab topology. A relative topology path and a relative `--write` path
are resolved from the invocation directory. `NODE1` and `NODE2` must be
declared in that topology, must be distinct, and must have a direct node-to-node
link. The capture joins `NODE1`'s network namespace and selects its endpoint
interface from that link. This observes packets on the node-side veth; it does
not capture unrelated host traffic.

If a pair has multiple direct links, select the NODE1-side port with
`--interface`, for example:

```bash
eclab sniff --topology labs/edge.clab.yml edge-a edge-b --interface eth2 -nn tcp port 179
```

`-t` is a short alias for `--topology` and is intended before the node pair.

Topology links must name their node-side interfaces in `endpoints`, as standard
Containerlab link declarations do. The command uses the retained derived
topology for a deployed lab when eclab's topology writer created one.

## Completion

Shell completion reads the selected topology without contacting Docker. At the
first node it offers every declared node; at the second it offers only direct
neighbors of the first and describes each link with both endpoint interface
names (for example, `fpx:port3 ↔ clbr:eth2`).
After the pair it offers supported tcpdump options,
common BPF filter terms, direction values for `-Q`, direct-link interfaces,
`--wireshark`, and path completion for topology and pcap output selectors.

Use `--` to mark the tcpdump portion when that makes the boundary clearer. The
plugin also recognizes its own selectors before `--` without the delimiter.
Completion after arbitrary BPF expressions is intentionally keyword-based; it
does not try to parse a full BPF expression or complete arbitrary hostnames.

## Live Wireshark streaming

Use `--wireshark` to launch the host's `wireshark` executable and start a live
capture:

```bash
eclab sniff r1 h1 --wireshark -Q in tcp port 179
```

The plugin exposes the selected link through a temporary Wireshark extcap
interface. Wireshark's Stop button stops tcpdump and removes the Docker helper;
Start or Restart begins a fresh capture. Closing Wireshark exits the command
and removes the temporary interface. Ctrl-C in the terminal also stops the
capture. The package installs the `eclab-sniff-extcap` helper used by Wireshark;
no persistent Wireshark configuration is needed.
Normal Docker pull progress and tcpdump status lines are kept out of the extcap
pipe; helper diagnostics are forwarded there only when the capture fails.

For this mode, Wireshark and its `dumpcap` capture executable must be installed
on the host; `wireshark` must be available on `PATH`. Existing Wireshark extcap
search paths are kept available for the launched instance. Use Wireshark's Save
As command to save packets from the GUI.
`--wireshark` and `--write` are mutually exclusive.

On Linux, `<launcher> sudoless` also checks whether `dumpcap` has an existing,
root-owned capture group configured for group execution. If so, it adds the
current user to that group; log out and back in before using `--wireshark`.
The command does not change `dumpcap` ownership, mode, or capabilities, and it
does not install Wireshark. If the installed package has not configured a
capture group, enable its non-root capture setup through the operating-system
package manager first. This grants host packet-capture access to the account.

The plugin sanitizes all tcpdump arguments. Tcpdump capture options such as
`-c`, `-s`, `-B`, and `-Q` affect the capture. A BPF filter supplied on the
`eclab sniff` command is active from the first packet. A capture filter entered
in Wireshark is also validated and applied by tcpdump. Wireshark display filters
and decoding preferences remain GUI controls.

## Supported tcpdump arguments

The plugin always fixes the capture interface, disables promiscuous mode, and
disables address-name lookups. It accepts these safe display options:

```text
-n -nn -e -q -v -vv -vvv -A -X -XX -x -xx -l -U -tt -ttt -tttt
```

It accepts these value options:

```text
-c COUNT       1 through 1,000,000 packets
-s SNAPLEN     0 through 262,144 bytes
-B BUFFER_KIB  1 through 16,384 KiB
-Q DIRECTION   in, out, or inout
```

Put tcpdump options before the BPF expression. All remaining tokens form the
filter. The plugin passes them as separate process arguments and places tcpdump
`--` before the filter; it never evaluates them through a shell. Filters are
limited to 128 tokens and 4,096 total UTF-8 bytes, with no control characters
and no token larger than 1,024 bytes.

The plugin rejects options that can change the selected interface, read or
write arbitrary files, load filter files, launch post-rotation commands, or
change user/security handling. In particular, `-i`, `-w`, `-r`, `-F`, `-z`,
`-Z`, `-C`, `-G`, and `-W` are not passed through. Use eclab's `--interface`
for link selection and `--write` for pcap output.

Examples:

```bash
eclab sniff r1 h1 -nn 'tcp port 179'
eclab sniff r1 h1 -- -s 0 icmp
eclab sniff r1 h1 --write captures/bgp.pcap -c 500 tcp port 179
eclab sniff r1 h1 --wireshark -Q in tcp port 179
```

The `--write` destination must be a new file in an existing directory. It is
created with mode `0600`; the plugin refuses to overwrite an existing path.
When tcpdump stops normally (including Ctrl-C), it flushes the capture. The
pcap remains on the host and must be removed by the operator when no longer
needed. Pcap bytes stream from the helper's stdout to this host file, so no
host directory or file is mounted into the helper.

## Requirements and lifecycle

The selected nodes must be running. The caller must be authorized to use the
Docker CLI and daemon. The plugin starts `nicolaka/netshoot:v0.16`, which
contains tcpdump; Docker pulls it if it is not cached, so registry access is
needed for the first use unless the image is preloaded. The helper shares only
NODE1's container network namespace, drops all Linux capabilities, then adds
`NET_RAW` for packet capture. It does not use host networking, mount the Docker
socket or pcap file, change lab containers, deploy a topology node, or request
privileged mode.

The helper runs in the foreground and Docker removes it when capture ends. No
plugin state, leases, or cleanup command are involved. `--write` creates the
requested host-side pcap; `--wireshark` opens the live capture in the host GUI;
without either option, tcpdump's decoded packet output appears in the terminal.

Access to a Docker daemon commonly grants broad host control. Use this command
only with a daemon and helper image you trust. Captures may contain credentials
or other sensitive packet data; the plugin writes pcap files privately and
does not rotate, upload, redact, or delete them.

## Troubleshooting

- `no direct node-to-node link`: check the topology's `links[].endpoints` and
  verify both nodes appear on the same direct link.
- `multiple links`: set `--interface` to one of NODE1's endpoint interfaces.
- `node ... was not found`: check the topology name, node declaration, and that
  the selected topology belongs to the deployed lab.
- `node ... is not running`: deploy or start the lab before capturing.
- Docker reports a permission error: grant the invoking user access to the
  selected Docker daemon; eclab itself does not elevate or invoke sudo.
- Wireshark reports `Couldn't run dumpcap in child process: Permission denied`:
  check that the current user can execute `dumpcap`. On Debian or Ubuntu, run
  `sudo dpkg-reconfigure wireshark-common`, select **Yes** for non-superuser
  capture, then run `<launcher> sudoless` and log out and back in. Do not run
  the Wireshark GUI as root.
- tcpdump reports an unsupported option: remove it or use a supported option
  above. The plugin deliberately rejects tcpdump's file, process, and interface
  override flags.

The base topology remains ordinary
[Containerlab YAML](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
