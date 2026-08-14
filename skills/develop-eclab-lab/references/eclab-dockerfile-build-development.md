# Plugin Instructions

This directory contains the `engulf-clab-dockerfile-build` plugin distribution.

## Purpose

The plugin builds a node's declared Docker image from a Dockerfile before
`engulf-clab deploy`. A node without a Dockerfile declaration may reuse an
image tag built for another node.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin ID: `engulf_clab.dockerfile_build`

Derive `<PREFIX>` from callback-bound `api.application.short_product_name`,
falling back to `api.application.product`; the official application uses
`ECLAB` and a short product name of `acme clab` uses `ACME_CLAB`.
The plugin runs `docker build` during `prepare_call()` only and must never build
during analysis. Acquire one multi-lease context covering every image tag before
launching parallel workers; callback-bound API lease contexts must not overlap.
Read `TopologySession.materialize()` during preparation so earlier topology
injectors can contribute packaged Dockerfile recipes.
