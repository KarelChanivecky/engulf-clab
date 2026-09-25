# Contributing

Keep this package free of the Engulf runtime and individual feature packages.
Context objects are immutable; contributor metadata must be YAML-safe and must
never contain plaintext secrets. Freeze hooks operate on a copy. Defrost hooks
must verify all input before changing staging so the caller can publish atomically.

State paths in contributor contexts belong to the contributor's namespace. The
orchestrator resolves that namespace; contributors must not infer sibling paths
or accidentally read the freeze plugin's private state.

Keep image source discovery separate from mutation contributors and deploy
execution. Image descriptors are immutable and contain no runtime handles;
missing inputs remain representable. Shared manifest validation performs only
bounded metadata parsing and streamed hashing, never extraction or Docker work.
Run API, freeze, image-archive, Dockerfile, and vrnetlab consumer tests when these
descriptors or the manifest format change.

Runtime provider discovery belongs in `runtime.py`. Keep the protocol independent
of concrete editions and reject an entry-point name that differs from its
provider's `edition`. The provider owns tool capture, compatibility checks,
mode artifacts, recipient preparation, and launcher generation.
