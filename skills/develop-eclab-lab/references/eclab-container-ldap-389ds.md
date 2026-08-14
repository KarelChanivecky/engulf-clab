# eclab.containers/ldap-389ds

LDAP management node for eclab-managed appliance labs: 389 Directory Server
with a Cockpit browser management UI. One co-located Linux node runs both.
Keep LDAP on the appliance-facing data-plane segment and expose only Cockpit
to the host.

## Contents

- `Dockerfile`: Fedora image with `389-ds-base`, `cockpit`, `cockpit-389-ds`,
  `openldap-clients`, `sudo`, `dbus-daemon`, and network/debug tools.
- `ldap_start.sh`: container entrypoint (`/usr/local/bin/ldap-start`). On
  first run it creates one local 389 DS instance, creates the configured
  suffix backend, enables the MemberOf plugin, restarts the instance, waits
  for LDAP readiness, and seeds entries; then it starts DBus/polkit and
  Cockpit on port `9090`. Runs under restart policies: an existing instance
  is simply started, not recreated.
- `seed.ldif`: default seed with `ou=people`/`ou=group`, two inetOrgPerson
  users, and nested `groupOfNames` groups, baked to `/etc/dirsrv/seed.ldif`.
  Labs replace the suffix, users, and groups with their own LDIF via a bind
  mount.

## Environment

All settings have working defaults; labs override them per node:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LDAP_INSTANCE` | `localhost` | 389 DS instance name (`slapd-<name>`) |
| `LDAP_BASE_DN` | `dc=lab,dc=local` | suffix to create and serve |
| `LDAP_DM_DN` | `cn=Directory Manager` | directory manager bind DN |
| `LDAP_DM_PASSWORD` | `admin123` | directory manager password |
| `LDAP_SEED_LDIF` | `/etc/dirsrv/seed.ldif` | LDIF applied on first run only |
| `COCKPIT_ADMIN_USER` | `admin` | local Linux user for Cockpit login |
| `COCKPIT_ADMIN_PASSWORD` | `admin` | that user's password |

`ldap_start.sh` derives the instance FQDN from `LDAP_BASE_DN` (for example
`dc=lab,dc=local` becomes `ldap.lab.local`).

## Topology

Put the node on the appliance LDAP-side link with a static address, and
publish Cockpit only:

```yaml
ldap:
  kind: linux
  image: eclab.containers/ldap-389ds
  ports:
    - 9090:9090
  env:
    LDAP_BASE_DN: "dc=lab,dc=local"
    LDAP_DM_PASSWORD: "admin123"
  binds:
    - configs/seed.ldif:/etc/dirsrv/seed.ldif:ro
  exec:
    - ip addr add <ldap-ip>/<prefix> dev eth1
    - ip link set eth1 up
```

```yaml
- endpoints: ["ldap:eth1", "fgt:<ldap-port>"]
```

Do not publish LDAP `389` or `636` to the host unless the user explicitly
asks; the directory is for the appliance-facing segment. Open the management
UI at `http://127.0.0.1:9090/` and log in with the `COCKPIT_ADMIN_USER`
credentials (`admin/admin` by default).

Use `cn=Directory Manager` only for directory administration. For appliance
authentication, seed normal users such as
`uid=user1,ou=people,<base-dn>` and reference them from the appliance LDAP
server object, user group, and auth policy/profile objects.

## Seeding Rules

When seeding groups, the entrypoint enables the 389 DS MemberOf plugin and
restarts the instance **before** running `ldapadd`, so users expose reverse
`memberOf` memberships. If you ever enable MemberOf after groups already
exist, run a MemberOf fixup task for the suffix or the affected users.

Replace the baked-in `seed.ldif` wholesale per lab rather than editing the
recipe: the seed contains lab FQDNs, mail domains, passwords, and group
memberships that belong to the consuming lab.

## Cockpit In Containers

For Cockpit in a non-systemd container, the entrypoint avoids the full system
pages: it keeps the UI focused on `389-console`, runs DBus/polkit directly,
proxies `/run/cockpit/session` for Cockpit session activation, and moves
nonessential Cockpit modules (`systemd`, `packagekit`, `apps`, `metrics`,
`users`) aside so they cannot crash the bridge.

## Questions To Ask The User

Before wiring this node into a lab, ask:

- Whether an appliance or management system must be able to fetch or synchronize directory
  records from LDAP.
- Separately, whether the user explicitly wants a multi-server 389 DS
  replication topology. Do not infer additional LDAP nodes from a request to
  enable replication or synchronization for an appliance or management system.
- Which domains/suffixes to seed, for example `dc=lab,dc=local`.
- Which users and groups to seed, including bind passwords and group
  memberships.

## Replication

Only if the user explicitly requests multiple directory servers or a
multi-supplier/consumer 389 DS topology:

- Seed a dedicated replication bind entry, for example
  `cn=replication manager,cn=config`, with a lab password chosen or approved
  by the user.
- Configure 389 DS replication for the requested suffixes and peers; do not
  assume replication when there is only one directory node.
- Add extra LDAP nodes only after the user explicitly requests
  directory-server peers, failover, or a multi-server replication test. The
  words "enable replication" alone, when describing an appliance or management system record
  retrieval, are insufficient authorization to add nodes.
- Add only the appliance LDAP config needed to authenticate against the
  replicated directory when the lab requires appliance integration. Keep
  appliance config minimal: LDAP server object, user group, and referenced
  auth policy/profile objects only.
