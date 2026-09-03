# Contributing

Keep this package free of the Engulf runtime and individual feature packages.
Context objects are immutable; contributor metadata must be YAML-safe and must
never contain plaintext secrets. Freeze hooks operate on a copy. Defrost hooks
must verify all input before changing staging so the caller can publish atomically.
