# engulf-executable-wrapper

`engulf-executable-wrapper` provides `ExecutableWrapperGoal`, a goal that invokes an
executable while preserving Engulf's managed plugin lifecycle.

This goal runtime targets Linux. Its process-group behavior, forwarded POSIX signal
set, and Bash/Zsh completion integration are deliberate goal-level platform
requirements; the `engulf` plugin framework itself is OS-independent.

## Wrapping A Command

```python
from engulf import ApplicationDefinition, PluginPolicy
from engulf_executable_wrapper import ExecutableWrapperGoal


def make_goal() -> ExecutableWrapperGoal:
    return ExecutableWrapperGoal("containerlab")


WRAPPER_APPLICATION = ApplicationDefinition(
    application_id="com.example.containerlab",
    display_name="clab",
    goal_factory=make_goal,
    vendor="Example Corp",
    product="Containerlab Wrapper",
    short_product_name="clab",
    version="1.0.0",
    plugin_policy=PluginPolicy.declared(),
)


def main() -> int:
    with WRAPPER_APPLICATION.create() as application:
        return application.run()
```

Keep the definition in a script-free core module and let each console launcher
create and close a fresh application. Importing the definition then has no discovery,
goal setup, or process side effects.

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

`ExecutableWrapperGoal(executable, *, completion_provider=None)` accepts a nonempty
text command or path. A bare command is resolved through `PATH` for each invocation; a
path is expanded for `~` and made absolute. The optional provider supplies fallback
completion for the wrapped command when the shell has no native completion. The
`executable` and `completion_provider` properties expose that configuration;
`arguments` and `completions` expose the setup-owned metadata registries used by
completion integration.

The goal's `contract`, `setup()`, and `achieve()` implement the managed `Goal`
lifecycle and are called by `Application`; application code should not invoke them
directly.

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

Execution is shell-free. The child inherits the wrapper's standard streams,
environment, current directory, controlling terminal, and process group. The runtime
does not capture child output or create a new session. Direct recursion is reported
as a spawn failure with exit 126.

The wrapper maps call outcomes to framework results as follows:

| Call outcome | `GoalResultStatus` | Exit |
| --- | --- | ---: |
| Child exited, including nonzero | `COMPLETED` | Child exit |
| Plugin preemption | `REJECTED` | Selected preemption exit |
| Not found | `FAILED` | `127` |
| Permission, recursion, or other spawn error | `FAILED` | `126` |
| Child signal | `FAILED` | `min(255, 128 + signal)` |
| Lifecycle, phase, validation, or cleanup error | `FRAMEWORK_FAILED` | `70` |

`after_call` runs for preemption, spawn failure, child signal, and normal child exit.
If analysis or preparation itself raises, that phase stops and no synthetic
after-call outcome is created; outer lifecycle cleanup and framework-failure handling
still run.

## Help

When an exact `--help` argument is present, the goal invokes the executable with the
original arguments. Plugin edits and preemption are ignored, and preparation is
skipped. After the executable's output, Engulf appends logging options and nonempty
plugin help blocks collected during setup. Each block appears in its own visibly
separated section headed by the plugin's stable ID. Values such as `--help=topic`
remain normal arguments.

Analyzers still run in help mode and see `CallMode.HELP`, so they must remain
side-effect free. `after_call` also runs with the help outcome before the wrapper
appends its own sections. The child exit remains the invocation exit.

## Completion

The goal mirrors existing Bash and Zsh completion for the wrapped executable and
merges plugin candidates. Wrapper-only options are removed from the completion
context sent to native executable completion.

Generate a script after installing this distribution:

```console
engulf-completion bash my-wrapper > ~/.local/share/bash-completion/completions/my-wrapper
engulf-completion zsh my-wrapper > ~/.local/share/zsh/site-functions/_my-wrapper

# Or let the generator write the file:
engulf-completion bash my-wrapper \
  --output ~/.local/share/bash-completion/completions/my-wrapper
```

The generator invokes the wrapper through a private environment protocol to discover
the wrapped executable. Source generated Bash completion after the wrapped command's
native completion. For Zsh, place the file on `fpath` before `compinit` or source it
after `compinit`.

Application-defined binary providers are used only when no native completion was
found. Static and dynamic plugin candidates are merged and deduplicated.

The generator executes the wrapper once to discover its configured executable and
returns 1 when the wrapper cannot launch, reports a nonzero inspection exit, or
returns an invalid description. Its `wrapper` argument may be a command or path.

Applications can render a script without running the inspection CLI:

```python
from engulf_executable_wrapper import render_completion_script
from engulf_executable_wrapper_api import Shell

script = render_completion_script(
    Shell.BASH,
    wrapper_command="my-wrapper",
    binary_service="wrapped-command",
)
```

`binary_service` is the native completion service name, normally the basename of
the configured executable. Both names must be nonempty and NUL-free. The
`ENGULF_INTERNAL_*` environment protocol embedded in generated scripts is private;
applications and plugins must not call or extend it.

Wrapper-only registered options and their values are hidden from native completion
before `--` unless their `OptionSpec` explicitly sets
`visible_to_binary_completion=True`. Options after `--` remain native arguments.
When native completion exists, it supplies binary candidates and suppresses the
application's fallback binary provider; plugin option, static, and dynamic
candidates are still merged.

## Writing Plugins

Depend on `engulf-executable-wrapper-api`, not this runtime package. The complete
plugin class, immutable contribution model, lifecycle rules, and reusable wheel
metadata are documented in
[`engulf-executable-wrapper-api/README.md`](executable-wrapper-api.md).

## Public Import Surface

`engulf_executable_wrapper` exports only `ExecutableWrapperGoal` and
`render_completion_script`. Import `Shell`, events, outcomes, contribution types,
registries, and the plugin base from `engulf_executable_wrapper_api`. Import
`ApplicationDefinition`, policies, and runtime configuration from `engulf`.
