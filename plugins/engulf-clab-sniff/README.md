# engulf-clab-sniff

Adds `eclab sniff` to capture traffic on a direct link between two deployed
Containerlab nodes. A disposable Docker helper shares node1's network namespace
and runs tcpdump on the interface that faces node2. Captures can stream live to
the host's Wireshark GUI with `--wireshark`; Wireshark's Stop and Restart
controls manage the tcpdump helper lifecycle. When installed, the plugin also
extends the `sudoless` command to add the current user to an already configured
Wireshark capture group.

See [USAGE.md](USAGE.md) for installation and the operator contract, and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation guidance.
