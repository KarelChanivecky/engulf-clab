# Plugin Instructions

This plugin produces a shareable archive without ever changing the source lab.
Never place license files, license pool paths, allocations, or clamps in a frozen
artifact. Keep the archive build staged and atomic so a failed freeze cannot leave
a partial output at its requested destination.
