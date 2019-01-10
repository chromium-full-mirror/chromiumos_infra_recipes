This subdirectory contains support code that is called from recipes and
DOES NOT PROVIDE A STABLE API outside of this repository.

The `deploy_cipd.sh` script is used to deploy updated support tools. After
it runs the resulting `deploy_cipd.json` file should be checked in with the
tool changes.
