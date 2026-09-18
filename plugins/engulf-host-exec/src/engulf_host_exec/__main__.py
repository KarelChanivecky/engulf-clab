"""Docker child launcher for portable shell entry points."""

import os
import sys

from . import docker_command


def main() -> None:
    command = docker_command(("docker", *sys.argv[1:]))
    os.execvp(command[0], list(command))


if __name__ == "__main__":
    main()
