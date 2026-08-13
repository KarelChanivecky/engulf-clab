# Container Manager Plugin Instructions

This is the only plugin that turns declarative container collections into
topology mutations. Keep collection discovery under normal Engulf activation,
accept only typed fields from `engulf-clab-containers-api`, and never mutate the
source topology. It must run after collections and the lab parser, and before
the Dockerfile builder and lab writer.
