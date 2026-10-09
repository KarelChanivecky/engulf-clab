# Contributing

`src/engulf_clab_port_check/plugin.py` owns port conflict detection, optional
interactive/automatic remapping, and successful-deploy ownership records. The
topology parser owns selection, environment expansion, and the invocation-scoped
`TOPOLOGY_CONTEXT`; this plugin consumes that session and must not parse another
copy of the source file.

The dependency entry points position this plugin after the parser and before
the writer. `analyze_call()` only strips wrapper-owned options from deploy
arguments. Keep live inspection and prompts in `prepare_call()`, and use the
parser's editor so the writer serializes the replacement into its temporary
topology without changing the user's source. All operational diagnostics use
callback-bound `api.logger`; the terminal input function is only for the
requested interactive answer.

Port parsing intentionally accepts numeric `host:container` values with TCP or
UDP. The socket probe must match the declared transport and close immediately.
Use live bind results as authoritative; workspace records only identify a
possible owner and require a currently running Docker lab before naming it.
Commit records after goal success, replacing the prior record set for that
topology. Keep automatic choices in the invocation plan and report them after
successful deployment.

Do not claim ports, hold sockets open, or edit the user's source topology. Keep
the noninteractive path failing clearly and the auto path selecting a distinct
open port for each same-protocol mapping. Update `USAGE.md` alongside changes to
flags, state, port syntax, or prompt behavior. Never run a real deploy.
