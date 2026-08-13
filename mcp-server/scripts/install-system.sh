#!/usr/bin/env bash
# Install the root systemd unit and an initial local-only eclab MCP configuration.
set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config_path="/etc/eclab-mcp/config.toml"
unit_path="/etc/systemd/system/eclab-mcpd.service"
# Do not resolve root-owned executables through a caller-controlled sudo PATH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
daemon_path="$(command -v eclab-mcpd || true)"
eclab_path="$(command -v eclab || true)"
containerlab_path="$(command -v containerlab || true)"
docker_path="$(command -v docker || true)"
start_service=1
interactive=0
declare -a lab_roots=()
declare -a users=()
declare -a profile_names=("default")
declare -A profile_environment=()
declare -A profile_secrets=()
declare -A profile_keys=()

usage() {
    printf '%s\n' \
        'Usage: install-system.sh [--interactive] [--lab-root ID=ABSOLUTE_PATH] [options]' \
        '' \
        'Options:' \
        '  --interactive            Collect an initial configuration in this terminal' \
        '  --lab-root ID=PATH       Add a configured topology root (repeatable, required for new noninteractive config)' \
        '  --user USER              Add a local user to the eclab-mcp group (repeatable)' \
        '  --daemon PATH            Absolute eclab-mcpd executable path' \
        '  --eclab PATH             Absolute eclab executable path' \
        '  --containerlab PATH      Absolute containerlab executable path' \
        '  --docker PATH            Absolute docker executable path' \
        '  --no-start               Install without enabling or starting the service' \
        '  -h, --help               Show this help' \
        '' \
        'The guided mode only creates a configuration when none exists. Existing' \
        '/etc/eclab-mcp/config.toml files are deliberately left unchanged.'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --interactive)
            interactive=1
            shift
            ;;
        --lab-root)
            [[ $# -ge 2 ]] || { echo "error: --lab-root requires ID=PATH" >&2; exit 2; }
            lab_roots+=("$2")
            shift 2
            ;;
        --user)
            [[ $# -ge 2 ]] || { echo "error: --user requires a local account" >&2; exit 2; }
            users+=("$2")
            shift 2
            ;;
        --daemon)
            [[ $# -ge 2 ]] || { echo "error: --daemon requires a path" >&2; exit 2; }
            daemon_path="$2"
            shift 2
            ;;
        --eclab)
            [[ $# -ge 2 ]] || { echo "error: --eclab requires a path" >&2; exit 2; }
            eclab_path="$2"
            shift 2
            ;;
        --containerlab)
            [[ $# -ge 2 ]] || { echo "error: --containerlab requires a path" >&2; exit 2; }
            containerlab_path="$2"
            shift 2
            ;;
        --docker)
            [[ $# -ge 2 ]] || { echo "error: --docker requires a path" >&2; exit 2; }
            docker_path="$2"
            shift 2
            ;;
        --no-start)
            start_service=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unsupported argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ${EUID} -ne 0 ]]; then
    echo "error: run this installer as root" >&2
    exit 1
fi

require_root_owned_tree() {
    local candidate="$1"
    while :; do
        local owner permissions
        owner="$(stat -c '%u' -- "$candidate")"
        permissions="$(stat -c '%a' -- "$candidate")"
        if [[ "$owner" != 0 || $((8#$permissions & 8#22)) -ne 0 ]]; then
            echo "error: root service executable path must be root-owned and not group- or world-writable: $candidate" >&2
            exit 1
        fi
        [[ "$candidate" == "/" ]] && return
        candidate="${candidate%/*}"
        [[ -n "$candidate" ]] || candidate="/"
    done
}

require_executable() {
    local label="$1"
    local path="$2"
    if [[ -z "$path" || ! "$path" =~ ^/[A-Za-z0-9._/+:-]+$ || ! -x "$path" ]]; then
        echo "error: $label must be an absolute executable path using safe path characters" >&2
        exit 1
    fi
    local resolved
    resolved="$(readlink -f -- "$path")"
    if [[ ! "$resolved" =~ ^/[A-Za-z0-9._/+:-]+$ || ! -x "$resolved" ]]; then
        echo "error: $label resolves to an unsafe executable path" >&2
        exit 1
    fi
    require_root_owned_tree "$resolved"
    printf '%s\n' "$resolved"
}

toml_quote() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '"%s"' "$value"
}

validate_root_spec() {
    local root_spec="$1"
    local root_id="${root_spec%%=*}"
    local root_path="${root_spec#*=}"
    if [[ "$root_id" == "$root_spec" || ! "$root_id" =~ ^[A-Za-z0-9_-]{1,64}$ || ! "$root_path" =~ ^/[A-Za-z0-9._/+:-]+$ || ! -d "$root_path" || -L "$root_path" ]]; then
        return 1
    fi
}

append_lab_root() {
    local root_spec="$1"
    local root_id="${root_spec%%=*}"
    local existing
    if ! validate_root_spec "$root_spec"; then
        return 1
    fi
    for existing in "${lab_roots[@]}"; do
        if [[ "${existing%%=*}" == "$root_id" ]]; then
            return 1
        fi
    done
    lab_roots+=("$root_spec")
}

ask_yes_no() {
    local prompt="$1"
    local default="$2"
    local answer
    while :; do
        read -r -p "$prompt" answer || return 1
        answer="${answer,,}"
        if [[ -z "$answer" ]]; then
            answer="$default"
        fi
        case "$answer" in
            y|yes)
                return 0
                ;;
            n|no)
                return 1
                ;;
            *)
                echo "Please answer yes or no." >&2
                ;;
        esac
    done
}

read_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    read -r -p "$prompt [$default]: " result || return 1
    printf '%s' "${result:-$default}"
}

append_profile_entry() {
    local profile="$1"
    local kind="$2"
    local name="$3"
    local value="$4"
    local existing
    existing="${profile_keys["$profile:$name"]:-}"
    if [[ -n "$existing" ]]; then
        return 1
    fi
    profile_keys["$profile:$name"]=1
    if [[ "$kind" == "secret" ]]; then
        if [[ -n "${profile_secrets[$profile]:-}" ]]; then
            profile_secrets[$profile]+=$'\n'
        fi
        profile_secrets[$profile]+="$name=$value"
    else
        if [[ -n "${profile_environment[$profile]:-}" ]]; then
            profile_environment[$profile]+=$'\n'
        fi
        profile_environment[$profile]+="$name=$value"
    fi
}

collect_profile() {
    local profile="$1"
    local variable value kind
    echo "Configure profile '$profile'. It starts empty; service-owned variables are optional."
    while ask_yes_no "Add a variable to profile '$profile'? [y/N] " "n"; do
        while :; do
            read -r -p 'Variable name: ' variable || return 1
            if [[ "$variable" =~ ^[A-Za-z_][A-Za-z0-9_]{0,127}$ ]]; then
                if [[ -n "${profile_keys["$profile:$variable"]:-}" ]]; then
                    echo "That profile already defines $variable." >&2
                else
                    break
                fi
            else
                echo "Use an environment-variable name (letters, digits, underscores; not starting with a digit)." >&2
            fi
        done
        if ask_yes_no "Keep $variable secret and non-overridable by MCP callers? [y/N] " "n"; then
            kind="secret"
            read -r -s -p "Value for $variable (hidden): " value || return 1
            printf '\n'
        else
            kind="environment"
            read -r -p "Value for $variable: " value || return 1
        fi
        if [[ "$value" =~ [[:cntrl:]] ]]; then
            echo "Environment values cannot contain control characters." >&2
            continue
        fi
        append_profile_entry "$profile" "$kind" "$variable" "$value"
    done
}

collect_initial_config() {
    if [[ ! -t 0 || ! -t 1 ]]; then
        echo "error: --interactive requires a terminal" >&2
        exit 2
    fi
    echo "Collecting the initial eclab MCP configuration. This grants the selected users access to all configured lab roots."

    if [[ ${#lab_roots[@]} -eq 0 ]]; then
        while :; do
            local root_id root_path
            root_id="$(read_with_default 'Lab-root ID' 'labs')" || exit 1
            read -r -p 'Lab-root absolute directory: ' root_path || exit 1
            if append_lab_root "$root_id=$root_path"; then
                break
            fi
            echo "Use a unique ID and an existing, non-symlink absolute directory." >&2
        done
    fi
    while ask_yes_no "Add another lab root? [y/N] " "n"; do
        local root_id root_path
        read -r -p 'Lab-root ID: ' root_id || exit 1
        read -r -p 'Lab-root absolute directory: ' root_path || exit 1
        if ! append_lab_root "$root_id=$root_path"; then
            echo "Use a unique ID and an existing, non-symlink absolute directory." >&2
        fi
    done

    if [[ ${#users[@]} -eq 0 ]]; then
        local default_user="${SUDO_USER:-${USER:-}}"
        while :; do
            local user_name
            user_name="$(read_with_default 'Local user allowed to use eclab-mcp' "$default_user")" || exit 1
            if id "$user_name" >/dev/null 2>&1; then
                users+=("$user_name")
                break
            fi
            echo "That local user does not exist." >&2
        done
    fi
    while ask_yes_no "Add another local MCP operator? [y/N] " "n"; do
        local user_name
        read -r -p 'Local user: ' user_name || exit 1
        if id "$user_name" >/dev/null 2>&1; then
            users+=("$user_name")
        else
            echo "That local user does not exist." >&2
        fi
    done

    collect_profile "default"
    while ask_yes_no 'Add another named invocation profile? [y/N] ' "n"; do
        local profile
        while :; do
            read -r -p 'Profile name: ' profile || exit 1
            if [[ "$profile" =~ ^[A-Za-z0-9_-]{1,64}$ && -z "${profile_environment[$profile]+set}" && -z "${profile_secrets[$profile]+set}" && "$profile" != "default" ]]; then
                break
            fi
            echo "Use a unique profile name of letters, digits, underscores, or hyphens." >&2
        done
        profile_names+=("$profile")
        # Mark an otherwise empty profile as present before checking another name.
        profile_environment[$profile]=""
        collect_profile "$profile"
    done
}

validate_lab_roots() {
    local root_spec root_id
    declare -A seen=()
    for root_spec in "${lab_roots[@]}"; do
        root_id="${root_spec%%=*}"
        if ! validate_root_spec "$root_spec" || [[ -n "${seen[$root_id]:-}" ]]; then
            echo "error: --lab-root must use a unique ID=existing-safe-absolute-directory" >&2
            exit 2
        fi
        seen[$root_id]=1
    done
}

validate_users() {
    local user_name
    for user_name in "${users[@]}"; do
        if ! id "$user_name" >/dev/null 2>&1; then
            echo "error: local user does not exist: $user_name" >&2
            exit 1
        fi
    done
}

render_mapping() {
    local profile="$1"
    local kind="$2"
    local entries entry name value first=1
    if [[ "$kind" == "secret" ]]; then
        entries="${profile_secrets[$profile]:-}"
    else
        entries="${profile_environment[$profile]:-}"
    fi
    printf '{'
    while IFS= read -r entry || [[ -n "$entry" ]]; do
        [[ -n "$entry" ]] || continue
        name="${entry%%=*}"
        value="${entry#*=}"
        if [[ $first -eq 0 ]]; then
            printf ', '
        fi
        first=0
        printf '%s = ' "$name"
        toml_quote "$value"
    done <<< "$entries"
    printf '}'
}

write_initial_config() {
    local temporary_config root_spec root_id root_path profile
    validate_lab_roots
    install -d -m 0755 /etc/eclab-mcp
    temporary_config="$(mktemp /etc/eclab-mcp/.config.XXXXXX)"
    {
        printf '%s\n' '# Root-owned eclab MCP configuration. Keep mode 0600.'
        printf '%s\n' '[service]'
        printf '%s\n' 'socket_path = "/run/eclab-mcp/eclab-mcp.sock"'
        printf '%s\n' 'socket_group = "eclab-mcp"'
        printf 'eclab_binary = '; toml_quote "$eclab_path"; printf '\n'
        printf 'containerlab_binary = '; toml_quote "$containerlab_path"; printf '\n'
        printf 'docker_binary = '; toml_quote "$docker_path"; printf '\n'
        printf '%s\n' 'state_dir = "/var/lib/eclab-mcp"'
        printf '%s\n' 'log_dir = "/var/log/eclab-mcp"'
        printf '%s\n' 'runtime_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"'
        printf '%s\n' 'job_retention_days = 14'
        printf '%s\n' 'max_job_log_bytes = 2097152'
        printf '%s\n' 'max_rpc_frame_bytes = 65536'
        printf '%s\n' 'max_read_output_bytes = 65536'
        printf '%s\n' 'read_timeout_seconds = 30'
        printf '%s\n' 'cancel_grace_seconds = 10'
        for root_spec in "${lab_roots[@]}"; do
            root_id="${root_spec%%=*}"
            root_path="${root_spec#*=}"
            printf '\n[[lab_roots]]\n'
            printf 'id = '; toml_quote "$root_id"; printf '\n'
            printf 'path = '; toml_quote "$root_path"; printf '\n'
        done
        for profile in "${profile_names[@]}"; do
            printf '\n[profiles.%s]\n' "$profile"
            printf 'environment = '; render_mapping "$profile" environment; printf '\n'
            printf 'secrets = '; render_mapping "$profile" secret; printf '\n'
        done
    } > "$temporary_config"
    install -m 0600 "$temporary_config" "$config_path"
    rm -f "$temporary_config"
    echo "Created $config_path."
}

daemon_path="$(require_executable "eclab-mcpd" "$daemon_path")"
eclab_path="$(require_executable "eclab" "$eclab_path")"
containerlab_path="$(require_executable "containerlab" "$containerlab_path")"
docker_path="$(require_executable "docker" "$docker_path")"

if ! getent group eclab-mcp >/dev/null; then
    groupadd --system eclab-mcp
fi

if [[ ! -e "$config_path" ]]; then
    if [[ $interactive -eq 1 ]]; then
        collect_initial_config
    fi
    if [[ ${#lab_roots[@]} -eq 0 ]]; then
        echo "error: --lab-root is required when creating $config_path (or use --interactive)" >&2
        exit 2
    fi
    validate_users
    write_initial_config
    "$daemon_path" --config "$config_path" --check-config
else
    echo "Keeping existing $config_path unchanged."
fi

for user_name in "${users[@]}"; do
    usermod --append --groups eclab-mcp "$user_name"
done

escaped_daemon="${daemon_path//\\\\/\\\\\\\\}"
escaped_daemon="${escaped_daemon//&/\\&}"
temporary_unit="$(mktemp /etc/systemd/system/.eclab-mcpd.XXXXXX)"
sed "s|@ECLAB_MCPD@|$escaped_daemon|g" "$package_dir/systemd/eclab-mcpd.service" > "$temporary_unit"
install -m 0644 "$temporary_unit" "$unit_path"
rm -f "$temporary_unit"

systemctl daemon-reload
if [[ $start_service -eq 1 ]]; then
    systemctl enable --now eclab-mcpd.service
    echo "Installed and started eclab-mcpd.service. New group members must log in again."
else
    echo "Installed eclab-mcpd.service without starting it."
fi
