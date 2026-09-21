# Contributing

Keep this package free of the Engulf runtime and individual feature packages.
Context objects are immutable; contributor metadata must be YAML-safe and must
never contain plaintext secrets. Freeze hooks operate on a copy. Defrost hooks
must verify all input before changing staging so the caller can publish atomically.

Keep image source discovery separate from mutation contributors and deploy
execution. Image descriptors are immutable and contain no runtime handles;
missing inputs remain representable. Shared manifest validation performs only
bounded metadata parsing and streamed hashing, never extraction or Docker work.
Run API, freeze, image-archive, Dockerfile, and vrnetlab consumer tests when these
descriptors or the manifest format change.
