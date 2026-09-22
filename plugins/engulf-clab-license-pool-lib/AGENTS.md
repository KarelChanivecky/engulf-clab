# Library instructions

This package is the framework-neutral pool-manager/state contract. It must not
import `engulf`, `engulf_api`, Containerlab parser/writer packages, or perform
filesystem, logging, or state-store I/O. The `engulf-clab-license-pool`
package owns those concerns and adapts its state representation here.

Keep the serialized entry fields (`allocations`, `history`, `clamped`,
`round_robin_index`, `last_used`, and `usage_sequence`) stable. Pool discovery
and manager mutation belong behind `PoolManager`; selection strategy belongs to
the concrete `PoolSelector` implementation in the product plugin.
