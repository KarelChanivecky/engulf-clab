# engulf-clab-sticky-ip

Adds stable, private Containerlab management addresses to eclab deployments.
IPv4 is selected by default; IPv6 and complete opt-out modes are available.
Availability probes use OS strategies backed by Python's standard library.
Linux uses UDP error queues; unavailable probes are skipped with an info message.

- [Operator usage](USAGE.md)
- [Contributor guide](CONTRIBUTING.md)
