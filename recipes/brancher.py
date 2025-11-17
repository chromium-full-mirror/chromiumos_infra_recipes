# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for creating a new ChromeOS branch."""

from typing import Generator

from PB.chromiumos.branch import Branch
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import (
    CrosReleaseConfigProperties,)
from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import (
    Email,)
from PB.recipes.chromeos.brancher import BrancherProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    "recipe_engine/properties",
    "recipe_engine/raw_io",
    "recipe_engine/step",
    "cros_branch",
    "cros_release_config",
    "cros_source",
    "depot_tools/gsutil",
    "easy",
    "workspace_util",
]


PROPERTIES = BrancherProperties


def is_108_or_greater(source_version: str) -> bool:
  return int(source_version.split("-")[1].split(".")[0]) >= 15183


def is_unsupported_rubik_build(api: RecipeApi, source_version: str) -> bool:
  # Support all builds associated with milestones >= 108.
  if is_108_or_greater(source_version):
    return False
  # Otherwise, only allow legacy builds.
  # Legacy build does not generate build_report.json but Rubik build does.
  # The gsutil will fail with URL matched no objects exception on a legacy
  # build.
  gs_path = "gs://chromeos-image-archive/atlas-kernelnext-release/{}/build_report.json".format(
      source_version)
  ret = api.gsutil.stat(gs_path, ok_ret="any")
  return ret.retcode == 0


def validate_properties(api: RecipeApi, properties: BrancherProperties) -> None:
  """Fail early if the build's input properties are invalid."""
  with api.step.nest("validate properties"):
    if not properties.source_version:
      raise StepFailure("source_version required")
    if properties.branch_info.type not in [
        Branch.RELEASE,
        Branch.STABILIZE,
        Branch.FIRMWARE,
        Branch.CUSTOM,
    ]:
      raise StepFailure("unsupported branch type: {}".format(
          properties.branch_info.type))
    # Legacy tryjob CLI does not work on branches created from Rubik buildspecs,
    # see b/252809202.
    if properties.branch_info.type == Branch.STABILIZE:
      if is_unsupported_rubik_build(api, properties.source_version):
        raise StepFailure(
            "temporary: do not cut stabilize branches from Rubik buildspecs "
            "(b/252809202 for context)")


def create_branch(api: RecipeApi, properties: BrancherProperties) -> str:
  """Create a new branch as specified by the input properties.

    Returns:
      The name of the newly created branch.
    """
  with api.step.nest("create branch") as presentation:
    branch_name = api.cros_branch.create_from_buildspec(
        properties.source_version,
        branch=properties.branch_info,
        push=properties.branch_util_push,
        force=properties.branch_util_force,
    )
    if not branch_name:
      raise StepFailure("branch name could not be parsed from branch_util")
    presentation.step_text = "Created branch {}".format(branch_name)
    api.easy.set_properties_step(branch_name=branch_name)
  return branch_name


def _should_update_release_config(properties: BrancherProperties) -> bool:
  """Determine whether we need to update the ChromeOS Release Config."""
  # No need to update config if no branch was actually created.
  if not properties.branch_util_push:
    return False
  # No need to update config for stabilize branches from < R108, as this is only
  # used with `cros try`, and `cros try` doesn't support builds from < R108.
  if (properties.branch_info.type == Branch.STABILIZE and
      not is_108_or_greater(properties.source_version)):
    return False
  # Custom branch types are weird and might break things.
  # Don't assume they should go into the scheduler.
  if properties.branch_info.type == Branch.CUSTOM:
    return False
  return True


def update_release_config(api: RecipeApi, properties: BrancherProperties,
                          branch_name: str) -> None:
  """Update the ChromeOS Release Config to include the new builder."""
  with api.workspace_util.setup_workspace():
    api.cros_source.ensure_synced_cache(
        projects=[api.cros_release_config.CONFIG_PROJECT])
    api.cros_release_config.update_config(
        branch_name,
        auto_submit=properties.autosubmit_config,
        dryrun=properties.abandon_cl,
    )


def create_summary_markdown(properties: BrancherProperties,
                            branch_name: str) -> result_pb2.RawResult:
  """Report on the final status of the builder."""
  if properties.branch_util_push:
    return result_pb2.RawResult(
        summary_markdown=f"Created branch: {branch_name}",
        status=common_pb2.SUCCESS,
    )
  return result_pb2.RawResult(
      summary_markdown="No new branch created",
      status=common_pb2.SUCCESS,
  )


def RunSteps(api: RecipeApi, properties: BrancherProperties) -> None:
  validate_properties(api, properties)
  branch_name = create_branch(api, properties)
  if _should_update_release_config(properties):
    update_release_config(api, properties, branch_name)
  return create_summary_markdown(properties, branch_name)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  TEST_STDOUT = """
2021/02/16 23:10:18.736295 No branch exists for version 13729.0.0. Continuing...
2021/02/16 23:10:18.744031 Creating branch: release-R89-13729.B
2021/02/16 23:10:19 Repairing manifest project chromiumos/manifest
"""

  yield api.test(
      "release-branch",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 89/13729.0.0.xml",
          stdout=api.raw_io.output_text(TEST_STDOUT),
      ),
      api.properties(
          BrancherProperties(
              source_version="R89-13729.0.0",
              branch_info=Branch(type=Branch.RELEASE),
              branch_util_push=True,
          )),
      api.post_check(
          post_process.StepCommandContains,
          "create branch."
          "create branch from buildspec manifest 89/13729.0.0.xml",
          ["create", "--buildspec-manifest", "89/13729.0.0.xml", "--release"],
      ),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "custom-branch",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 89/13729.0.0.xml",
          stdout=api.raw_io.output_text(TEST_STDOUT),
      ),
      api.properties(
          BrancherProperties(
              source_version="R89-13729.0.0",
              branch_info=Branch(type=Branch.CUSTOM, name="foo"),
              branch_util_push=True,
              autosubmit_config=True,
          )),
      api.post_check(post_process.DoesNotRun, "update config"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "stabilize-branch-descriptor",
      api.step_data("validate properties.gsutil stat", retcode=1),
      api.step_data(
          "create branch"
          ".create branch from buildspec manifest 89/13729.0.0.xml",
          stdout=api.raw_io.output_text(TEST_STDOUT),
      ),
      api.properties(
          BrancherProperties(
              source_version="R89-13729.0.0",
              branch_info=Branch(
                  type=Branch.STABILIZE,
                  name="this should not be used anywhere",
                  descriptor="foo",
              ),
              branch_util_push=True,
              autosubmit_config=True,
          )),
      api.post_check(
          post_process.StepCommandContains,
          "create branch."
          "create branch from buildspec manifest 89/13729.0.0.xml",
          [
              "create",
              "--buildspec-manifest",
              "89/13729.0.0.xml",
              "--stabilize",
              "--descriptor",
              "foo",
          ],
      ),
  )

  yield api.test(
      "no-source-version",
      api.properties(
          BrancherProperties(branch_info=Branch(type=Branch.RELEASE))),
      api.post_check(post_process.StepFailure, "validate properties"),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "bad-branch-type",
      api.properties(
          BrancherProperties(
              source_version="R89-13729.0.0",
              branch_info=Branch(type=Branch.FACTORY),
          )),
      api.post_check(post_process.StepFailure, "validate properties"),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "bad-branch-stablize-rubik-build",
      api.step_data("validate properties.gsutil stat", retcode=0),
      api.properties(
          BrancherProperties(
              source_version="R107-15000.0.0",
              branch_info=Branch(type=Branch.STABILIZE),
          )),
      api.post_check(post_process.StepFailure, "validate properties"),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "good-branch-stablize-rubik-build",
      api.properties(
          BrancherProperties(
              source_version="R109-15194.0.0",
              branch_info=Branch(type=Branch.STABILIZE),
              branch_util_push=True,
          )),
      api.step_data(
          "create branch"
          ".create branch from buildspec manifest 109/15194.0.0.xml",
          stdout=api.raw_io.output_text(TEST_STDOUT),
      ),
      api.post_check(post_process.StepSuccess, "validate properties"),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "bad-branch_util-run",
      api.properties(
          BrancherProperties(
              source_version="R89-13729.0.0",
              branch_info=Branch(type=Branch.RELEASE),
          )),
      api.post_check(post_process.StepFailure, "create branch"),
      # TODO (b/275363240): audit this test.
      status="FAILURE",
  )

  yield api.test(
      "firmware-branch",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 126/15885.0.0.xml",
          stdout=api.raw_io.output_text("""
2024/06/03 19:49:23.411775 Fetched working manifest.
2024/06/03 19:49:23.411876 Using sourceRevision 96fa0117101484ffc5c92138bdf4ad1b84b476fe for manifestInternal
2024/06/03 19:49:23.411883 Using sourceUpstream main for manifestInternal
2024/06/03 19:49:23.570772 Version found: 15885.0.0.
2024/06/03 19:49:23.570798 Have manifest = &{manifest-internal chromeos/manifest-internal 96fa0117101484ffc5c92138bdf4ad1b84b476fe refs/heads/main cros-internal [{no-branch-suffix true}]   []}
2024/06/03 19:49:24.517851 No branch exists for version 15885.0.0. Continuing...
2024/06/03 19:49:24.527978 Creating branch: firmware-R126-15885.B
2024/06/03 19:49:25.320741 Repairing manifest project chromiumos/manifest
2024/06/03 19:49:28.993146 Repairing manifest project chromeos/manifest-internal
2024/06/03 19:53:14.208866 Created 1040 of 1040 remote branches
2024/06/03 20:07:04.208732 Bump CHROMEOS_BRANCH number after creating branch firmware-R126-15885.B
2024/06/03 20:07:04.208788 Bump CHROMEOS_BUILD number for source branch main after creating branch firmware-R126-15885.B
2024/06/03 20:07:04.208796 completed successfully
"""),
      ),
      api.properties(
          **{
              "$chromeos/cros_release_config":
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jbettis@google.com")],
                      ccs=[Email(email="chromeos-firmware@google.com")],
                      keep_n_milestones=3,
                  ),
              "source_version":
                  "R126-15885.0.0",
              "branch_info":
                  Branch(type=Branch.FIRMWARE, descriptor="R126"),
              "branch_util_push":
                  True,
          }),
      api.post_check(
          post_process.StepCommandContains,
          "create branch."
          "create branch from buildspec manifest 126/15885.0.0.xml",
          [
              "create",
              "--buildspec-manifest",
              "126/15885.0.0.xml",
              "--firmware",
              "--descriptor",
              "R126",
              "--skip-group-check",
              "--push",
          ],
      ),
  )

  yield api.test(
      "firmware-ec-branch",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 126/15886.2.0.xml",
          stdout=api.raw_io.output_text("""
2024/06/03 19:49:23.411775 Fetched working manifest.
2024/06/03 19:49:23.411876 Using sourceRevision 96fa0117101484ffc5c92138bdf4ad1b84b476fe for manifestInternal
2024/06/03 19:49:23.411883 Using sourceUpstream main for manifestInternal
2024/06/03 19:49:23.570772 Version found: 15886.2.0.
2024/06/03 19:49:23.570798 Have manifest = &{manifest-internal chromeos/manifest-internal 96fa0117101484ffc5c92138bdf4ad1b84b476fe refs/heads/main cros-internal [{no-branch-suffix true}]   []}
2024/06/03 19:49:24.517851 No branch exists for version 15886.2.0. Continuing...
2024/06/03 19:49:24.527978 Creating branch: firmware-ec-R126-15886.2.B
2024/06/03 19:49:25.320741 Repairing manifest project chromiumos/manifest
2024/06/03 19:49:28.993146 Repairing manifest project chromeos/manifest-internal
2024/06/03 19:53:14.208866 Created 1040 of 1040 remote branches
2024/06/03 20:07:04.208732 Bump CHROMEOS_BRANCH number after creating branch firmware-ec-R126-15886.2.B
2024/06/03 20:07:04.208788 Bump CHROMEOS_BUILD number for source branch main after creating branch firmware-ec-R126-15886.2.B
2024/06/03 20:07:04.208796 completed successfully
"""),
      ),
      api.properties(
          **{
              "$chromeos/cros_release_config":
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jbettis@google.com")],
                      ccs=[Email(email="chromeos-firmware@google.com")],
                      keep_n_milestones=3,
                  ),
              "source_version":
                  "R126-15886.2.0",
              "branch_info":
                  Branch(type=Branch.FIRMWARE, descriptor="R126"),
              "branch_util_push":
                  True,
          }),
      api.post_check(
          post_process.StepCommandContains,
          "create branch."
          "create branch from buildspec manifest 126/15886.2.0.xml",
          [
              "create",
              "--buildspec-manifest",
              "126/15886.2.0.xml",
              "--firmware",
              "--descriptor",
              "R126",
              "--skip-group-check",
              "--push",
          ],
      ),
  )

  yield api.test(
      "firmware-milestone-branch",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 126/15886.2.0.xml",
          stdout=api.raw_io.output_text("""
2024/06/03 19:49:23.411775 Fetched working manifest.
2024/06/03 19:49:23.411876 Using sourceRevision 96fa0117101484ffc5c92138bdf4ad1b84b476fe for manifestInternal
2024/06/03 19:49:23.411883 Using sourceUpstream main for manifestInternal
2024/06/03 19:49:23.570772 Version found: 15886.2.0.
2024/06/03 19:49:23.570798 Have manifest = &{manifest-internal chromeos/manifest-internal 96fa0117101484ffc5c92138bdf4ad1b84b476fe refs/heads/main cros-internal [{no-branch-suffix true}]   []}
2024/06/03 19:49:24.517851 No branch exists for version 15886.2.0. Continuing...
2024/06/03 19:49:24.527978 Creating branch: firmware-R126-15886.2.B
2024/06/03 19:49:25.320741 Repairing manifest project chromiumos/manifest
2024/06/03 19:49:28.993146 Repairing manifest project chromeos/manifest-internal
2024/06/03 19:53:14.208866 Created 1040 of 1040 remote branches
2024/06/03 20:07:04.208732 Bump CHROMEOS_BRANCH number after creating branch firmware-R126-15886.2.B
2024/06/03 20:07:04.208788 Bump CHROMEOS_BUILD number for source branch main after creating branch firmware-R126-15886.2.B
2024/06/03 20:07:04.208796 completed successfully
"""),
      ),
      api.properties(
          **{
              "$chromeos/cros_release_config":
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jbettis@google.com")],
                      ccs=[Email(email="chromeos-firmware@google.com")],
                      keep_n_milestones=3,
                  ),
              "source_version":
                  "R126-15886.2.0",
              "branch_info":
                  Branch(type=Branch.FIRMWARE, descriptor="R126"),
              "branch_util_push":
                  True,
          }),
      api.post_check(
          post_process.StepCommandContains,
          "create branch."
          "create branch from buildspec manifest 126/15886.2.0.xml",
          [
              "create",
              "--buildspec-manifest",
              "126/15886.2.0.xml",
              "--firmware",
              "--descriptor",
              "R126",
              "--skip-group-check",
              "--push",
          ],
      ),
  )

  yield api.test(
      "firmware-branch-no-descriptor",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 126/15885.0.0.xml",
          stdout=api.raw_io.output_text("""
2024/06/03 19:49:23.411775 Fetched working manifest.
2024/06/03 19:49:23.411876 Using sourceRevision 96fa0117101484ffc5c92138bdf4ad1b84b476fe for manifestInternal
2024/06/03 19:49:23.411883 Using sourceUpstream main for manifestInternal
2024/06/03 19:49:23.570772 Version found: 15885.0.0.
2024/06/03 19:49:23.570798 Have manifest = &{manifest-internal chromeos/manifest-internal 96fa0117101484ffc5c92138bdf4ad1b84b476fe refs/heads/main cros-internal [{no-branch-suffix true}]   []}
2024/06/03 19:49:24.517851 No branch exists for version 15885.0.0. Continuing...
2024/06/03 19:49:24.527978 Creating branch: firmware-15885.B
2024/06/03 19:49:25.320741 Repairing manifest project chromiumos/manifest
2024/06/03 19:49:28.993146 Repairing manifest project chromeos/manifest-internal
2024/06/03 19:53:14.208866 Created 1040 of 1040 remote branches
2024/06/03 20:07:04.208732 Bump CHROMEOS_BRANCH number after creating branch firmware-15885.B
2024/06/03 20:07:04.208788 Bump CHROMEOS_BUILD number for source branch main after creating branch firmware-15885.B
2024/06/03 20:07:04.208796 completed successfully
"""),
      ),
      api.properties(
          **{
              "$chromeos/cros_release_config":
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jbettis@google.com")],
                      ccs=[Email(email="chromeos-firmware@google.com")],
                      keep_n_milestones=3,
                  ),
              "source_version":
                  "R126-15885.0.0",
              "branch_info":
                  Branch(type=Branch.FIRMWARE),
              "branch_util_push":
                  True,
          }),
      api.post_check(post_process.StepFailure,
                     "validate branch.validate firmware branch"),
      status="FAILURE",
  )

  yield api.test(
      "no-branch_util_push",
      api.step_data(
          "create branch."
          "create branch from buildspec manifest 126/15886.2.0.xml",
          stdout=api.raw_io.output_text("""
2024/06/03 19:49:23.411775 Fetched working manifest.
2024/06/03 19:49:23.411876 Using sourceRevision 96fa0117101484ffc5c92138bdf4ad1b84b476fe for manifestInternal
2024/06/03 19:49:23.411883 Using sourceUpstream main for manifestInternal
2024/06/03 19:49:23.570772 Version found: 15886.2.0.
2024/06/03 19:49:23.570798 Have manifest = &{manifest-internal chromeos/manifest-internal 96fa0117101484ffc5c92138bdf4ad1b84b476fe refs/heads/main cros-internal [{no-branch-suffix true}]   []}
2024/06/03 19:49:24.517851 No branch exists for version 15886.2.0. Continuing...
2024/06/03 19:49:24.527978 Creating branch: firmware-R126-15886.2.B
2024/06/03 19:49:25.320741 Repairing manifest project chromiumos/manifest
2024/06/03 19:49:28.993146 Repairing manifest project chromeos/manifest-internal
2024/06/03 19:53:14.208866 Created 1040 of 1040 remote branches
2024/06/03 20:07:04.208732 Bump CHROMEOS_BRANCH number after creating branch firmware-R126-15886.2.B
2024/06/03 20:07:04.208788 Bump CHROMEOS_BUILD number for source branch main after creating branch firmware-R126-15886.2.B
2024/06/03 20:07:04.208796 completed successfully
"""),
      ),
      api.properties(
          **{
              "$chromeos/cros_release_config":
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jbettis@google.com")],
                      ccs=[Email(email="chromeos-firmware@google.com")],
                      keep_n_milestones=3,
                  ),
              "source_version":
                  "R126-15886.2.0",
              "branch_info":
                  Branch(type=Branch.FIRMWARE, descriptor="R126"),
              "branch_util_push":
                  False,
          }),
  )
