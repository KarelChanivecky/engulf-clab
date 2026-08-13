# Core Container Collection Instructions

Recipes in this package are declarative `ContainerDefinition` values. Keep all
Docker build inputs inside the typed package and make runtime behavior generic,
environment-driven, and reusable across labs. The fixed collection plugin ID is
`eclab.containers`, which owns its image namespace.
