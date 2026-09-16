# engulf-clab-demo-lab

Installs one portable, broad-coverage eclab demonstration lab without
publishing an Engulf plugin of its own.

```bash
python3.12 -m pip install engulf-clab-demo-lab
eclab-demo-lab-install
cd eclab-demo-lab
./run-eclab.sh --help
```

The lab uses only Linux containers and public base images. It needs no
FortiGate image, license, or other proprietary VM input.

See [USAGE.md](USAGE.md) for the installed workflow and
[CONTRIBUTING.md](CONTRIBUTING.md) for package maintenance.
