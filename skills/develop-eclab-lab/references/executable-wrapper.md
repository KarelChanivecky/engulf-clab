# engulf-executable-wrapper

`engulf-executable-wrapper` provides `ExecutableWrapperGoal`, a goal that invokes an
executable while preserving Engulf's managed plugin lifecycle.

This goal runtime targets Linux. Its process-group behavior, forwarded POSIX signal
set, and Bash/Zsh completion integration are deliberate goal-level platform
requirements; the `engulf` plugin framework itself is OS-independent.

## Wrapping A Command

```python
from engulf import Application, PluginPolicy
from engulf_executable_wrapper import ExecutableWrapperGoal

application = Application(
    application_id="com.example.containerlab",
    goal=ExecutableWrapperGoal("containerlab"),
    display_name="clab",
    vendor="Example Corp",
    product="Containerlab Wrapper",
    short_product_name="clab",
    version="1.0.0",
    plugin_policy=PluginPolicy.declared(),
)


def main() -> int:
    return application.run()
```

The executable may be an explicit text path or a command resolved through `PATH`.
All invocation arguments pass through unchanged unless plugin contributions remove,
add, or preempt them.

When an application is elevated, all selected plugins and the wrapped child run
with that authority. Use only trusted plugin packages and prefer an explicit,
administrator-controlled executable path; do not rely on a `PATH` containing
locations writable by less-privileged users. Engulf currently provides no plugin
sandbox or trust grant mechanism.

`Application.invoke()` returns `GoalResult[CallOutcome]`. `Application.run()` returns
the executable, preemption, spawn-failure, or framework exit code.

## Behavior

For each normal invocation, the goal:

1. dispatches every plugin's side-effect-free `analyze_call`;
2. validates and merges all argument contributions;
3. resolves preemption before external preparation;
4. dispatches `prepare_call` only when execution remains viable;
5. executes the child while forwarding wrapper signals;
6. dispatches `after_call` in postprocessing order;
7. returns a typed outcome to outer `after_goal` middleware.

The child shares the wrapper's existing process group. This preserves controlling
terminal and shell job-control behavior. While the child is alive, temporary handlers
forward SIGHUP, SIGINT, SIGQUIT, SIGTERM, SIGUSR1, SIGUSR2, and SIGWINCH, then restore
the wrapper's previous handlers. Child termination by signal maps to `128 + signal`.

Spawn failures use conventional exits: 127 when not found and 126 when the executable
cannot be invoked. Directly resolving the executable to the wrapper itself is
rejected.

## Help

When an exact `--help` argument is present, the goal invokes the executable with the
original arguments. Plugin edits and preemption are ignored, and preparation is
skipped. After the executable's output, Engulf appends logging options and nonempty
plugin help blocks collected during setup. Each block appears in its own visibly
separated section headed by the plugin's stable ID. Values such as `--help=topic`
remain normal arguments.

## Completion

The goal mirrors existing Bash and Zsh completion for the wrapped executable and
merges plugin candidates. Wrapper-only options are removed from the completion
context sent to native executable completion.

Generate a script after installing this distribution:

```console
engulf-completion bash my-wrapper > ~/.local/share/bash-completion/completions/my-wrapper
engulf-completion zsh my-wrapper > ~/.local/share/zsh/site-functions/_my-wrapper
```

The generator invokes the wrapper through a private environment protocol to discover
the wrapped executable. Source generated Bash completion after the wrapped command's
native completion. For Zsh, place the file on `fpath` before `compinit` or source it
after `compinit`.

Application-defined binary providers are used only when no native completion was
found. Static and dynamic plugin candidates are merged and deduplicated.

## Writing Plugins

Depend on `engulf-executable-wrapper-api`, not this runtime package. The complete
plugin class, immutable contribution model, lifecycle rules, and reusable wheel
metadata are documented in
[`engulf-executable-wrapper-api/README.md`](../engulf-executable-wrapper-api/README.md).
