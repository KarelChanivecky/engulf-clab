# engulf-clab-demo-lab

Installs one comprehensive eclab demonstration lab without publishing an
Engulf plugin of its own.

```bash
python3.14 -m pip install engulf-clab-demo-lab
eclab-demo-lab-install --fortigate-image /path/to/fortios.qcow2
cd eclab-demo-lab
./run-eclab.sh --help
```

The FortiGate VM input and license are entitled operator inputs. The installer
records the image path but never copies it, and creates an empty license pool
for the operator to populate.

See [USAGE.md](USAGE.md) for the installed workflow and
[CONTRIBUTING.md](CONTRIBUTING.md) for package maintenance.
