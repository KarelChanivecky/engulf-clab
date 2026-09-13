# Sticky management IPs

Install `engulf-clab-sticky-ip` beside `engulf-clab`, or install the
`engulf-clab-all-plugins` meta-package. The plugin uses valid Containerlab YAML
fields and changes only the retained derived topology. The selected source YAML
is never edited.

`eclab deploy` and a single-topology `eclab redeploy` use sticky IPv4 by
default. Select IPv6 instead or bypass all sticky behavior with:

```bash
eclab deploy -t lab.clab.yml --eclab-sticky-ipv6
eclab deploy -t lab.clab.yml --eclab-no-sticky-ip
```

The switches persist as `ECLAB_STICKY_IPV6` and `ECLAB_NO_STICKY_IP`. Opt-out
wins when both are true. Sticky mode supports Docker; use the opt-out switch for
another Containerlab runtime. Management overrides `--network`,
`--ipv4-subnet`, and `--ipv6-subnet` are rejected because they would override
the checked derived values.

## Allocation configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `ECLAB_STICKY_IP_MAX_LABS` | `64` | Maximum active lab identities; twice this value is the retained logical-unit budget. |
| `ECLAB_STICKY_IPV4_POOL` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | Ordered comma-separated RFC1918 pools. |
| `ECLAB_STICKY_IPV6_POOL` | `fd00::/8` | Ordered comma-separated IPv6 ULA pools. |
| `ECLAB_STICKY_IP_EXCLUDES` | unset | Mixed comma-separated private IPs or CIDRs that no allocation may overlap. |

Pool variables replace their defaults. IPv4 entries must lie inside RFC1918;
IPv6 entries must lie inside `fc00::/7` and avoid bytes 5 through 8 of the
network prefix because Docker truncates those bytes. Empty, public,
overlapping, wrong-family, and undersized pools fail before deployment.

One logical block supports 128 management-attached nodes. It is a `/24` for
IPv4 or `/120` for IPv6, with offsets 2 through 129 reserved for nodes. Larger
labs take an aligned power-of-two number of blocks: 129–256 nodes use `/23` or
`/119`; 257–512 nodes use `/22` or `/118`. A smaller topology keeps its larger
historical allocation so existing addresses do not move.

The first deployment sorts node names. Later deployments preserve addresses by
node name, fill new nodes from the lowest free slot, and allow removed-node
slots to be reused. Nodes whose effective `network-mode` is `host`, `none`, or
`container:*` are not attached to the management network and receive no sticky
address.

Returning labs get their historical block first. New labs advance through the
configured pools, skipping exclusions and conflicts. When the retained window
is full, inactive historical blocks are reused in address order; active,
pending, and uncertain claims are never reused. The default network name is a
stable `eclab-mgmt-<hash>` derived from the canonical topology workspace and
lab name. A custom network name is preserved only when it is private to the lab
and compatible with the selected subnet.

## Explicit addressing

A topology may provide a complete selected-family setup. The plugin preserves
it and performs the same availability checks:

```yaml
name: fixed
mgmt:
  network: fixed-management
  ipv4-subnet: 10.44.0.0/24
topology:
  nodes:
    r1:
      kind: linux
      image: alpine
      mgmt-ipv4: 10.44.0.10
    r2:
      kind: linux
      image: alpine
      mgmt-ipv4: 10.44.0.11
```

The subnet must be private and every management-attached node must have a
unique in-range address. Partial fixed addressing, `auto`, reserved addresses,
and incomplete opposite-family addressing are rejected. A compatible complete
opposite family is preserved when the plugin adds the selected family.

## Availability and lifecycle

Before publication, eclab holds a user-wide allocator lease and checks its own
claims, all Docker network IPAM subnets and endpoints, and every IPv4 and IPv6
host route table. Two traceroutes run concurrently against spread addresses in
the candidate. Each trace is stopped after 100 ms and the entire candidate
search stops after one second. A responding destination or a router address
inside the candidate rejects that block. Silence is only an extra signal;
Docker and route overlap checks remain authoritative.

An unchanged address held by containers proven to belong to this exact lab is
allowed for repeat deployment and redeploy. A subnet change for a live lab
requires `redeploy` or `deploy --reconfigure`; `redeploy --keep-mgmt-net`
cannot change the retained network. `redeploy --all` and name-only redeploy
cannot rebuild one authoritative source topology and require per-topology calls
or `--eclab-no-sticky-ip`.

Claims are stored as versioned Engulf user state. A pending claim is rolled back
when preparation fails or Containerlab never starts. Once Containerlab starts,
an unsuccessful result remains reserved because partial host state may exist.
A successful destroy makes the lab's history reusable. `destroy --all` releases
all claims, while `--keep-mgmt-net` keeps them reserved. If a failed deployment
left an uncertain claim, run a successful destroy for that topology before
expecting the block to recycle.

Docker, `ip`, and `traceroute` must be available through the service-controlled
PATH. Failure to inspect any required source is fatal; the plugin never guesses
that a subnet is free.
