# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to automate kernel version bumps in the release-keys repository."""

from typing import Generator

from PB.chromite.api.signing import (
    KernelVersionBumpOp,
    KeysetManagerRequest,
    KeysetManagerResponse,
    KeysetOp,
    KeysetOpResult,
    MiniOsVersionBumpOp,
)
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.keyset_manager import KeysetManagerProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi, TestData

DEPS = [
    "recipe_engine/buildbucket",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "build_menu",
    "cros_build_api",
    "cros_try",
    "gerrit",
    "git",
    "signing",
    "src_state",
]

PROPERTIES = KeysetManagerProperties


def validate_properties(properties: KeysetManagerProperties) -> KeysetOp:
  """Validates input properties and returns the single requested KeysetOp."""
  if not properties.bug:
    raise StepFailure("`bug` is a required property.")

  if properties.keyset and properties.update_all:
    raise StepFailure("Cannot specify both `keyset` and `update_all`.")
  if not properties.keyset and not properties.update_all:
    raise StepFailure("Must specify either `keyset` or `update_all`.")

  if len(properties.operations) != 1:
    raise StepFailure("Must specify exactly one operation in `operations`.")

  operation = properties.operations[0]
  if not operation.WhichOneof("op"):
    raise StepFailure("Must specify a valid operation in `operations`.")

  return operation


def RunSteps(api: RecipeApi,
             properties: KeysetManagerProperties) -> result_pb2.RawResult:
  operation = validate_properties(properties)

  # Define path for release-keys repo
  release_keys_path = api.src_state.workspace_path.joinpath(
      "src/platform/signing/keys")

  # 1. Clone repositories
  with api.step.nest("clone release-keys"):
    api.git.clone(
        "https://chromium.googlesource.com/chromiumos/chromite/",
        target_path=api.src_state.workspace_path / "infra/chromite-HEAD",
        branch="main",
        single_branch=True,
    )

    api.git.clone(
        "https://chromium.googlesource.com/chromiumos/chromite/",
        target_path=api.src_state.workspace_path / "infra/chromite",
        branch="main",
        single_branch=True,
    )

    api.git.clone(
        "https://chrome-internal.googlesource.com/chromeos/platform/release-keys",
        target_path=release_keys_path,
        branch="main",
        single_branch=True,
    )

  dry_run = properties.dry_run or api.build_menu.is_staging
  executed_op = None

  if operation.HasField("kernel_version_bump"):
    executed_op = "KernelVersionBump"
    # 2. Call increment_kernel_version.py script
    script_path = release_keys_path.joinpath(
        "keyset/public/scripts/increment_kernel_version.py")

    script_args = ["--all"
                  ] if properties.update_all else ["-k", properties.keyset]
    script_args += ["-b", str(properties.bug)]

    with api.context(cwd=release_keys_path):
      with api.step.nest("increment kernel version"):
        cmd = ["vpython3", script_path] + script_args
        api.step("run increment_kernel_version.py", cmd)
  else:
    with api.step.nest("keyset manager docker operations"):
      api.step(
          "docker auth",
          [
              "gcloud",
              "auth",
              "configure-docker",
              "us-docker.pkg.dev",
          ],
      )

      api.step(
          "docker pull",
          [
              "docker",
              "pull",
              api.signing.signing_docker_image,
          ],
      )

      request = KeysetManagerRequest(
          dry_run=dry_run,
          release_keys_checkout=str(release_keys_path),
          bug=properties.bug,
          keyset="" if properties.update_all else properties.keyset,
      )
      request.docker_image = api.signing.signing_docker_image
      request.operations.append(operation)

      response = api.cros_build_api.SigningService.KeysetManager(request)

      regen_keyset = None
      if response.results:
        result = response.results[0]
        executed_op = result.op_name
        if result.status != KeysetOpResult.OP_STATUS_SUCCESS:
          raise StepFailure(
              f"Keyset operation {result.op_name} failed: {result.error_message}"
          )
        if properties.keyset and result.modified_files:
          regen_keyset = result.modified_files[0].split("/")[0]

      if response.status != KeysetManagerResponse.STATUS_SUCCESS:
        raise StepFailure(f"KeysetManager failed: {response.error_message}")

      regen_arg = f"../{regen_keyset}" if regen_keyset else "--all"
      with api.context(cwd=release_keys_path):
        api.step("regenerate_keysets.sh",
                 ["./keyset/public/scripts/regenerate_keysets.sh", regen_arg])

  # 3. Check for changes in the workspace
  with api.context(cwd=release_keys_path):
    diff_files = api.git.get_working_dir_diff_files()

    if not diff_files:
      return result_pb2.RawResult(
          summary_markdown="No keyset changes generated.",
          status=bb_common_pb2.FAILURE,
      )

    # 4. Commit changes
    target_desc = (f"for {properties.keyset}"
                   if properties.keyset else "for all boards")
    subject = f"firmware: Update keysets ({executed_op}) {target_desc}"

    commit_lines = [
        subject,
        "",
        "Generated by keyset_manager recipe.",
        f"See {api.buildbucket.build_url()} for job details.",
        "",
        f"Operation executed: {executed_op}",
    ]

    if dry_run:
      commit_lines += [
          "",
          "This CL was created as part of a dry run build, it is not meant to be submitted.",
      ]

    commit_lines += [
        "",
        f"BUG=b:{properties.bug}",
        "TEST=CQ",
    ]

    commit_message = "\n".join(commit_lines) + "\n"

    api.git.add_all()
    api.git.commit(commit_message)

    # 5. Upload Gerrit CL
    reviewers = [
        "croskeymanagers@google.com",
        "chromeos-automated-release-platform@google.com",
    ] if not api.build_menu.is_staging else []
    invoker = api.cros_try.get_invoker()

    change = api.gerrit.create_change(
        str(release_keys_path),
        project_path=release_keys_path,
        non_repo_checkout=True,
        reviewers=reviewers,
        ccs=[invoker] if invoker else [],
    )

    # 6. Abandon if dry run or staging
    if dry_run:
      api.gerrit.abandon_change(change)

  status_msg = "Abandoned dry run CL" if dry_run else "Created CL"
  return result_pb2.RawResult(
      summary_markdown=f"{status_msg} {api.gerrit.parse_gerrit_change_url(change)}",
      status=bb_common_pb2.SUCCESS,
  )


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  kernel_bump_op = [KeysetOp(kernel_version_bump=KernelVersionBumpOp())]
  minios_bump_op = [KeysetOp(minios_version_bump=MiniOsVersionBumpOp())]

  yield api.test(
      "basic",
      api.properties(
          KeysetManagerProperties(bug=12345, update_all=True,
                                  operations=kernel_bump_op)),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/board1.json\n"),
      api.post_check(post_process.MustRun, "clone release-keys"),
      api.post_check(post_process.MustRun, "increment kernel version"),
      api.post_check(
          post_process.StepCommandContains,
          "increment kernel version.run increment_kernel_version.py",
          ["--all", "-b", "12345"],
      ),
      api.post_check(post_process.MustRun, "git commit"),
      api.post_check(
          post_process.MustRun,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload"
      ),
      api.post_check(
          post_process.StepCommandContains,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload",
          [
              "--reviewers", "croskeymanagers@google.com", "--reviewers",
              "chromeos-automated-release-platform@google.com"
          ],
      ),
      api.post_check(post_process.SummaryMarkdownRE, r"Created CL"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "basic-board",
      api.properties(
          KeysetManagerProperties(bug=12345, keyset="atlas",
                                  operations=kernel_bump_op)),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/atlas.json\n"),
      api.post_check(post_process.MustRun, "clone release-keys"),
      api.post_check(post_process.MustRun, "increment kernel version"),
      api.post_check(
          post_process.StepCommandContains,
          "increment kernel version.run increment_kernel_version.py",
          ["-k", "atlas", "-b", "12345"],
      ),
      api.post_check(post_process.MustRun, "git commit"),
      api.post_check(
          post_process.MustRun,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload"
      ),
      api.post_check(post_process.SummaryMarkdownRE, r"Created CL"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "dry-run",
      api.properties(
          KeysetManagerProperties(bug=12345, update_all=True, dry_run=True,
                                  operations=kernel_bump_op)),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/board1.json\n"),
      api.post_check(post_process.MustRun, "git commit"),
      api.post_check(
          post_process.MustRun,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload"
      ),
      api.post_check(post_process.MustRun, "abandon CL 1"),
      api.post_check(post_process.SummaryMarkdownRE, r"Abandoned dry run CL"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "staging",
      api.properties(
          KeysetManagerProperties(bug=12345, update_all=True,
                                  operations=kernel_bump_op)),
      api.buildbucket.build(
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project="chromeos",
                  bucket="staging",
                  builder="staging-keyset-manager",
              ))),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/board1.json\n"),
      api.post_check(post_process.MustRun, "git commit"),
      api.post_check(
          post_process.MustRun,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload"
      ),
      api.post_check(
          post_process.StepCommandDoesNotContain,
          "create gerrit change for [CLEANUP]/chromiumos_workspace/src/platform/signing/keys.git_cl upload",
          ["--reviewers"],
      ),
      api.post_check(post_process.MustRun, "abandon CL 1"),
      api.post_check(post_process.SummaryMarkdownRE, r"Abandoned dry run CL"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "no-changes",
      api.properties(
          KeysetManagerProperties(bug=12345, update_all=True,
                                  operations=kernel_bump_op)),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(""),
      api.post_check(post_process.MustRun, "clone release-keys"),
      api.post_check(post_process.MustRun, "increment kernel version"),
      api.post_check(
          post_process.SummaryMarkdown,
          "No keyset changes generated.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "missing-bug",
      api.properties(KeysetManagerProperties()),
      api.post_check(
          post_process.SummaryMarkdown,
          "`bug` is a required property.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "both-specified",
      api.properties(
          KeysetManagerProperties(bug=12345, keyset="atlas", update_all=True)),
      api.post_check(
          post_process.SummaryMarkdown,
          "Cannot specify both `keyset` and `update_all`.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "neither-specified",
      api.properties(KeysetManagerProperties(bug=12345)),
      api.post_check(
          post_process.SummaryMarkdown,
          "Must specify either `keyset` or `update_all`.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "no-operations",
      api.properties(KeysetManagerProperties(bug=12345, update_all=True)),
      api.post_check(
          post_process.SummaryMarkdown,
          "Must specify exactly one operation in `operations`.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "multiple-operations",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              update_all=True,
              operations=kernel_bump_op + minios_bump_op,
          )),
      api.post_check(
          post_process.SummaryMarkdown,
          "Must specify exactly one operation in `operations`.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "empty-operation-oneof",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              update_all=True,
              operations=[KeysetOp()],
          )),
      api.post_check(
          post_process.SummaryMarkdown,
          "Must specify a valid operation in `operations`.",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "operations-specified",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              keyset="BryaMPKeys",
              operations=minios_bump_op,
          )),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/brya.json\n"),
      api.post_check(post_process.MustRun, "keyset manager docker operations"),
      api.post_check(post_process.MustRun,
                     "keyset manager docker operations.docker pull"),
      api.post_check(post_process.MustRun,
                     "keyset manager docker operations.regenerate_keysets.sh"),
      api.post_check(
          post_process.StepCommandContains,
          "keyset manager docker operations.regenerate_keysets.sh",
          [
              "./keyset/public/scripts/regenerate_keysets.sh",
              "../BryaMPKeys-v25"
          ],
      ),
      api.post_check(
          post_process.StepCommandContains,
          "write commit message",
          [
              "firmware: Update keysets (MiniOsVersionBump) for BryaMPKeys\n\n"
              "Generated by keyset_manager recipe.\n"
              "See https://cr-buildbucket.appspot.com/build/0 for job details.\n\n"
              "Operation executed: MiniOsVersionBump\n\n"
              "BUG=b:12345\n"
              "TEST=CQ\n"
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "operations-update-all",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              update_all=True,
              operations=minios_bump_op,
          )),
      api.git.use_mock(True),
      api.git.get_working_dir_diff_files(
          "M keyset/public/definitions/brya.json\n"),
      api.post_check(
          post_process.StepCommandContains,
          "keyset manager docker operations.regenerate_keysets.sh",
          ["./keyset/public/scripts/regenerate_keysets.sh", "--all"],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "operations-op-error",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              update_all=True,
              operations=minios_bump_op,
          )),
      api.cros_build_api.set_api_return(
          "keyset manager docker operations",
          "SigningService/KeysetManager",
          data='{"status": 2, "results": [{"status": 2, "op_name": "MiniOsVersionBump", "error_message": "mocked op error"}]}',
      ),
      api.git.use_mock(True),
      api.post_check(
          post_process.SummaryMarkdown,
          "Keyset operation MiniOsVersionBump failed: mocked op error",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "operations-response-error",
      api.properties(
          KeysetManagerProperties(
              bug=12345,
              update_all=True,
              operations=minios_bump_op,
          )),
      api.cros_build_api.set_api_return(
          "keyset manager docker operations",
          "SigningService/KeysetManager",
          data='{"status": 2, "error_message": "top-level container error"}',
      ),
      api.git.use_mock(True),
      api.post_check(
          post_process.SummaryMarkdown,
          "KeysetManager failed: top-level container error",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
