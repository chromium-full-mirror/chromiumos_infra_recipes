# `test_dagwood_firmware` Recipe

This recipe executes on-device ChromeOS EC firmware tests on **Dagwood**
hardware test fixtures attached to **Satlab** Swarming bots.

[TOC]

## Overview

The `test_dagwood_firmware` recipe orchestrates hardware-in-the-loop (HIL) EC
testing by launching the `ec-builder` Docker container on a Satlab host,
building and flashing Zephyr EC test images onto an attached EC Add-In Card
(AIC) via the Dagwood fixture, and reporting granular Twister test case results
to ResultDB.

### Repository Files

*   [`recipes/test_dagwood_firmware.proto`](../test_dagwood_firmware.proto):
    Defines the `TestDagwoodFirmwareProperties` input protobuf message.
*   [`recipes/test_dagwood_firmware.py`](../test_dagwood_firmware.py):
    Recipe entry point (`RunSteps` and `GenTests`). Wraps test execution with
    ResultDB (`ResultSink`) and surfaces pass/fail/skip counts and Milo links.
*   [`recipes/test_dagwood_firmware.resources/runner.py`](./runner.py):
    Bot-side Python runner executed inside the Satlab Swarming `drone`
    container. Communicates with the Satlab host Docker daemon over mutual TLS
    to run `ec-builder:latest`, stream logs, extract `twister.json`, and upload
    test results to ResultSink.

---

## Architecture & Execution Flow

On Satlab devices, LUCI Swarming tasks execute inside the `drone` container,
while hardware devices and the `ec-builder:latest` image are managed by the
Satlab host's Docker daemon (`192.168.231.1:2376`).

1.  **Docker TLS Connection**:
    `runner.py` loads client TLS certificates from `DOCKER_CERT_PATH` (default
    `/var/run/docker-certs`: `ca.pem`, `cert.pem`, `key.pem`) and connects to
    `https://192.168.231.1:2376`. (When TLS certificates are absent, such as in
    local simulation tests, `runner.py` simulates a passing run.)
2.  **Container Creation & Hardware Forwarding**:
    `runner.py` creates a privileged `ec-builder:latest` container
    (`POST /containers/create`) with the following bind mounts:
    *   `/usr/local/ec-workspace:/workspace`: Persistent host workspace storing
        the git checkouts (`src/platform/ec`, `src/platform/dagwood`,
        `src/third_party/zephyrproject`, etc.), Python `.venv`, Coreboot SDK
        toolchain cache (`.cache/coreboot-sdk`), and build/test outputs.
        > **Note:** On ChromeOS/Satlab, `/usr/local` (backed by
        > `/mnt/stateful_partition/dev_image`) is mounted with `exec`
        > permissions. Avoid placing the workspace directly under
        > `/mnt/stateful_partition/...`, which is mounted `noexec` and prevents
        > executing `./dagwood`, `.venv` binaries, and toolchain compilers.
    *   `/dev/bus/usb:/dev/bus/usb`: Grants direct USB access for querying the
        Dagwood board and sending vendor USB control transfers (MECC slot power,
        EC reset, and UART mux selection).
    *   `/dev/ttyACM*:/dev/ttyACM*`: Forwards all active CDC-ACM serial ports
        (Dagwood shell console, EC UART console bridge, EC bootloader/flash
        UART bridge, and ST-Link).
3.  **Test Execution & Log Streaming**:
    The container runs `./dagwood` from `/workspace/src/platform/ec`:
    ```bash
    cd /workspace/src/platform/ec && ./dagwood -p <platform> [-T <test_path>...] [-s <test_scenario>...] [<extra_args>...]
    ```
    `runner.py` attaches to `/containers/{id}/logs?stdout=1&stderr=1&follow=1`,
    demultiplexes Docker's 8-byte framed stdout/stderr stream in real time, and
    waits for container completion via `POST /containers/{id}/wait`.
4.  **Artifact Extraction & Cleanup**:
    Before deleting the container (`DELETE /containers/{id}?force=1`),
    `runner.py` fetches `/workspace/src/platform/ec/twister-out/twister.json`
    via the Docker archive API (`GET /containers/{id}/archive`).
5.  **ResultDB Reporting**:
    `runner.py` parses `twister.json` and reports each Zephyr `ztest` testcase
    to `ResultSink` (`luci.resultsink.v1.Sink/ReportTestResults`):
    *   **Test ID**: `chromeos.ec.<safe_platform>.<testcase_identifier>` (with
        `/` in platform names replaced by `.`, e.g.,
        `chromeos.ec.realtek.rts5912.aic.i2c.test_i2c_basic`).
    *   **Status**: `PASS`, `FAIL`, or `SKIP` (for `skipped`/`filtered`).
    *   **Tags**: `platform` (e.g., `realtek/rts5912`) and `suite` (e.g.,
        `aic.i2c`).
    *   **Bug Component**: IssueTracker component ID `167114`.
    *   **Summary & Failure Reason**: Includes Twister `reason` and escaped
        console `log` output on failures and skips.

---

## Input Properties

Configured via `TestDagwoodFirmwareProperties` in
[`test_dagwood_firmware.proto`](../test_dagwood_firmware.proto):

| Property | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `platform` | `repeated string` | Target EC platforms passed via `-p` to `./dagwood` (e.g., `"realtek/rts5912"`, `"npcx9/npcx9m7f"`, `"it8xxx2/it82002aw"`). | `["realtek/rts5912"]` |
| `test_path` | `repeated string` | Test directories relative to `src/platform/ec` passed via `-T` (e.g., `"zephyr/test/ec-aic"`). If both `test_path` and `test_scenario` are empty, all available tests for the platform are run. | `[]` |
| `test_scenario` | `repeated string` | Specific Twister test scenarios/suites passed via `-s` (e.g., `"aic.i2c"`). | `[]` |
| `extra_args` | `repeated string` | Additional arguments forwarded to `./dagwood` (e.g., `"--sram"`, `"-b"`). | `[]` |

### Example JSON Properties

```json
{
  "platform": ["realtek/rts5912"],
  "test_path": ["zephyr/test/ec-aic"],
  "test_scenario": ["aic.i2c"],
  "extra_args": ["--sram"]
}
```

---

## Satlab Host Prerequisites

Before running this recipe against a Satlab bot:

1.  **Deploy the `ec-builder:latest` Docker image** onto the Satlab host
    (see `src/platform/ec/docker/README.md` for building `ec-builder`):
    ```bash
    docker save ec-builder:latest | gzip -1 | ssh <satlab-host> /usr/local/bin/docker load
    ```
2.  **Verify `/usr/local/ec-workspace`** exists on the Satlab host (or allow
    `ec-builder` to populate it on first run).
3.  **Hardware Connection**: Ensure the Dagwood fixture (USB VID:PID
    `18d1:5214`) and target EC AIC are connected to the Satlab host.

---

## Development & Testing

### Running Recipe Unit Tests

From the `infra/recipes` directory:

```bash
# Run unit tests for this recipe
./recipes.py test run --filter test_dagwood_firmware

# Train expectation files and update generated docs (README.recipes.md)
./recipes.py test train --filter test_dagwood_firmware
```

If `cipd` (`depot_tools`) is not on your `PATH`, prepend the checkout's
`depot_tools`:

```bash
PATH="$(realpath ../../src/chromium/depot_tools):$PATH" \
  ./recipes.py test run --filter test_dagwood_firmware
```

### Testing on a Satlab Bot with `led`

You can test local recipe modifications directly against a Satlab bot in the
`ec-dagwood` pool using `led`.

Because `chromeos/test_runner/test_runner` runs in the `ChromeOSSkylab`
Swarming pool (where Satlab bots reside), use it as the base `JobDefinition`,
bundle your local recipe checkout with `led edit-recipe-bundle`, override the
recipe (`-r test_dagwood_firmware`) and pool dimension (`-d label-pool=ec-dagwood`),
strip conflicting `test_runner` properties, and set the executable to
`./luciexe`:

> **Note:** On gLinux workstations, `/usr/bin/led` is an unrelated system binary
> that shadows `depot_tools/led` if `depot_tools` appears after `/usr/bin` in
> `PATH` (failing with `led.go:257] No output specified, --fs_spool_path argument
> is required`). Prepend `depot_tools` to `PATH` before running the `led`
> pipeline.

```bash
export PATH="$(realpath ../../src/chromium/depot_tools):$PATH"

led get-builder chromeos/test_runner/test_runner | \
  led edit-recipe-bundle | \
  led edit \
    -r test_dagwood_firmware \
    -d label-pool=ec-dagwood \
    -p 'platform=["it8xxx2/it82002aw"]' \
    -p 'extra_args=["--sram"]' | \
  jq '
    del(.buildbucket.bbagent_args.build.input.properties |
        .config, .common_config, ."$chromeos/cts_results_archive",
        ."$chromeos/cros_tool_runner", ."$chromeos/phosphorus") |
    .buildbucket.bbagent_args.build.exe = {"cmd": ["./luciexe"]}
  ' | \
  led launch
```

*   **Milo Build Overview**: `https://ci.chromium.org/ui/b/<BUILD_ID>`
*   **All Test Results**:
    `https://ci.chromium.org/ui/b/<BUILD_ID>/test-results?q=ExactID%3A*`
    *(Note: The LUCI Milo Test Results tab defaults to filtering by "Unexpected
    only"; use the `?q=ExactID%3A*` query or the `Milo Test Results (All)` step
    link to view passing test cases as well.)*
