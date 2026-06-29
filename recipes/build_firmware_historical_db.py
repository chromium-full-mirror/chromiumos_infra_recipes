# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that manages Zephyr EC firmware's historical token database.

This recipe builds firmware and merges its unified database with the
historical database in GCS. This database maintenance runs on a
24 hour cadence.
"""

import re
from typing import NamedTuple

from PB.chromite.api.firmware import BuildAllFirmwareRequest
import PB.chromiumos.common as common_pb2
from PB.recipes.chromeos.build_firmware_historical_db import (
    BuildFirmwareHistoricalDbProperties,)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts
from RECIPE_MODULES.chromeos.gerrit.api import Label

DEPS = [
    "depot_tools/gsutil",
    "recipe_engine/bcid_reporter",
    "recipe_engine/buildbucket",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/json",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/raw_io",
    "recipe_engine/resultdb",
    "recipe_engine/step",
    "recipe_engine/time",
    "build_menu",
    "cros_artifacts",
    "cros_build_api",
    "cros_infra_config",
    "cros_sdk",
    "cros_source",
    "easy",
    "failures",
    "gcloud",
    "gerrit",
    "git",
    "repo",
    "src_state",
    "test_util",
]


PROPERTIES = BuildFirmwareHistoricalDbProperties


class GobConfig(NamedTuple):
  host: str
  project: str
  branch: str

PRECONDITION_FAILURE = 412
PACKAGE_NAME = "chromeos-ec-token"
HISTORICAL_DB = f"{PACKAGE_NAME}-historical.bin"
VERSIONED_DB = f"{PACKAGE_NAME}-%s.bin"

CHROMEOS_LOCALMIRROR = "gs://chromeos-localmirror"
# For staging builder
THROWAWAY_BUCKET = "gs://chromeos-throw-away-bucket"

DISTFILES = "distfiles"
TOKEN_BUCKET = f"{DISTFILES}/cros_ec/tokens"
TOKEN_VERSION_BUCKET = f"{TOKEN_BUCKET}/version"
PACKAGE_PATH = (
    "src/third_party/chromiumos-overlay/chromeos-base/chromeos-ec-token")
VERSION_FILE = f"{PACKAGE_PATH}/VERSION-PIN"


def RunSteps(api, properties):
  with (
      api.build_menu.configure_builder() as config,
      api.build_menu.setup_workspace(),
  ):
    api.build_menu.setup_chroot()

    if not properties.gob_host:
      raise StepFailure("gob_host property must be specified in builder config")
    if not properties.gob_project:
      raise StepFailure(
          "gob_project property must be specified in builder config")
    if not properties.gob_branch:
      raise StepFailure(
          "gob_branch property must be specified in builder config")

    service = api.cros_build_api.FirmwareService
    chroot = api.cros_sdk.chroot
    location = (
        properties.firmware_location or config.general.firmware_location)

    service.BuildAllFirmware(
        BuildAllFirmwareRequest(
            firmware_location=location,
            chroot=chroot,
            code_coverage=False,
        ),
        name="build firmware",
    )

    snapshot_sha = api.src_state.gitiles_commit.id
    api.easy.set_properties_step(got_revision=snapshot_sha,
                                 step_name="output got_revision")

    uploaded_artifacts, _ = api.build_menu.upload_artifacts(
        config=config,
        report_to_spike=api.cros_infra_config.config.artifacts
        .attestation_eligible,
    )

    gob_config = GobConfig(
        host=properties.gob_host,
        project=properties.gob_project,
        branch=properties.gob_branch,
    )

    UpdateHistoricalTokenDatabase(
        api,
        location,
        uploaded_artifacts,
        (THROWAWAY_BUCKET
         if api.build_menu.is_staging else CHROMEOS_LOCALMIRROR),
        gob_config=gob_config,
    )


def _GetStatInfo(api: RecipeApi, gsFile: str, field: str):

  def _GetField(name, output):
    m = re.search(r"%s:\s*(.+)" % re.escape(name), output.stdout)
    if m:
      return m.group(1)
    raise StepFailure('Field "%s" missing in "%s"' % (name, output.stdout))

  statOut = api.gsutil.stat(
      gsFile,
      stdout=api.raw_io.output_text(),
  )

  return _GetField(field, statOut)


def _GetGenerationId(api: RecipeApi, gsFile: str):
  return int(_GetStatInfo(api, gsFile, "Generation"))


def UpdateVersionPin(api: RecipeApi, version: str):
  with api.step.nest("update VERSION-PIN") as presentation:
    package_path = api.cros_source.workspace_path.joinpath(PACKAGE_PATH)
    version_path = api.cros_source.workspace_path.joinpath(VERSION_FILE)

    api.file.write_text("write version pin file", version_path, version)

    with (
        api.step.nest("commit version pin file"),
        api.context(cwd=api.path.abs_to_path(package_path)),
    ):
      project = api.repo.project_info(project=api.git.repository_root())
      api.repo.start("uprev-chromeos-ec-token-pin", projects=[project.name])

      message = (f"{api.path.basename(version_path)}: updating version pin "
                 f"{PACKAGE_NAME} to {version}\n\n")
      message += f"CL generated by job {api.buildbucket.build_url()}"

      api.git.add([version_path])
      api.git.commit(message)

      # Upload CL to gerrit as long as not in staging.
      if not api.build_menu.is_staging:
        with api.step.nest("upload CL to gerrit"):
          change = api.gerrit.create_change(project=project.name,
                                            topic=PACKAGE_NAME)
          labels = {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          }
          api.gerrit.set_change_labels(change, labels)

          presentation.links["CL"] = (
              api.gerrit.parse_gerrit_change_url(change))


def UploadEcTokenPrebuilts(
    api: RecipeApi,
    source_path: str,
    gob_config: GobConfig,
    abandon: bool = True,
) -> str:
  """Uploads the ec token prebuilts to the git repo.

    Returns:
      The message describing the upload result."""
  with api.step.nest("upload ec-token prebuilts") as presentation:
    checkout = api.path.mkdtemp()
    with api.context(cwd=checkout):
      api.git.clone(
          f"https://{gob_config.host}.googlesource.com/{gob_config.project.lstrip('/')}",
          depth=1,
      )

      # Copy the prebuilt into the ec-token prebuild repo.
      db_path = api.path.join(checkout, HISTORICAL_DB)
      api.file.copy("copy historical_db to repo", source_path, db_path)

      # Check to make sure there was actually a change.
      diff_lines = api.git.get_working_dir_diff_files()
      if not diff_lines:
        return "No ec-token prebuilts changed."
      # Create a cl updating the file.
      api.git.add([db_path])
      bbid = api.buildbucket.build_url()

      commit_msg = (f"ec-token: Update prebuilts\n\n"
                    f"Generated by {bbid}.\n")

      api.git.commit(commit_msg)
      change = api.gerrit.create_change(
          f"/{gob_config.project.lstrip('/')}",
          ref=api.git.get_branch_ref(gob_config.branch),
          project_path=checkout,
          non_repo_checkout=True,
          topic=PACKAGE_NAME,
      )
      if abandon:
        api.gerrit.abandon_change(change)
      else:
        labels = {
            Label.PRESUBMIT_READY: 1,
            Label.AUTOSUBMIT: 1,
        }
        api.gerrit.set_change_labels_remote(change, labels)

        presentation.links["CL"] = api.gerrit.parse_gerrit_change_url(change)
      return "Updated ec-token prebuilts"


def CopyVersionedDatabase(
    api: RecipeApi,
    source: str,
    gs_bucket: str,
    gob_config: GobConfig,
):
  with api.step.nest("Generate versioned database name"):
    file_hash = api.file.file_hash(source, test_data="deadbeef")
    version = api.time.utcnow().strftime("%Y.%m.%d.%H%M%S")
    # Apply some suffixes to avoid potential collisions for staging.
    file_hash += "-staging" if api.build_menu.is_staging else ""
    version += "_alpha" if api.build_menu.is_staging else ""

    gs_path_with_hash = (
        f"{gs_bucket}/{TOKEN_VERSION_BUCKET}/historical.{file_hash}.bin")

    cp_flags = ["--if-generation-match=0"]
    if not api.build_menu.is_staging:
      cp_flags.append("--predefined-acl=publicRead")

    retval = api.gcloud.storage_cp(
        source,
        gs_path_with_hash,
        flags=cp_flags,
        ok_ret=(0, 1, PRECONDITION_FAILURE),
    ).retcode

    # Update distfiles location when a new versioned database is copied.
    if retval == 0:
      api.gcloud.storage_cp(
          gs_path_with_hash,
          f"{gs_bucket}/{DISTFILES}/{HISTORICAL_DB}",
          flags=([
              "--predefined-acl=publicRead",
          ] if not api.build_menu.is_staging else None),
      )
      api.gcloud.storage_cp(
          gs_path_with_hash,
          f"{gs_bucket}/{DISTFILES}/{VERSIONED_DB % version}",
          flags=([
              "--predefined-acl=publicRead",
          ] if not api.build_menu.is_staging else None),
      )
      UpdateVersionPin(api, version)
      UploadEcTokenPrebuilts(
          api,
          source,
          gob_config,
          abandon=api.build_menu.is_staging,
      )


def UpdateHistoricalTokenDatabase(
    api: RecipeApi,
    location: common_pb2.FwLocation,
    uploaded_artifacts: UploadedArtifacts,
    gs_bucket: str,
    gob_config: GobConfig,
):
  """Updates Historical Token Database in GCS.

    Updates the historical database in GCS using preconditions
    to avoid any race conditions between other builders.

    Args:
      api: RecipesAPI object for dependencies.
      location: The firmware location.
      uploaded_artifacts: Artifacts that were uploaded.
      gs_bucket: GS bucket to upload token database.
    """
  if location == common_pb2.PLATFORM_ZEPHYR:
    cros_src_path = api.cros_source.workspace_path
    vpython_spec = cros_src_path.joinpath(
        "src/platform/ec/zephyr/pigweed-vpython3")
    pw_tokenizer = cros_src_path.joinpath(
        "src/third_party/pigweed/pw_tokenizer/py/pw_tokenizer/database.py")

    with api.step.nest("Update Historical Token Database"):
      if "FIRMWARE_TOKEN_DATABASE" in uploaded_artifacts.files_by_artifact:
        temp_dir = api.path.mkdtemp()
        token_dir = api.path.join(temp_dir, "token")
        api.file.ensure_directory("Create token download directory", token_dir)
        temp_historical_db = api.path.join(token_dir, HISTORICAL_DB)

        unified_dbs = uploaded_artifacts.files_by_artifact[
            "FIRMWARE_TOKEN_DATABASE"]

        local_unified_dbs = []
        for db in unified_dbs:
          api.gsutil.download(
              uploaded_artifacts.gs_bucket,
              f"{uploaded_artifacts.gs_path}/{db}",
              f"{token_dir}/{db}",
          )
          local_unified_dbs.append(f"{token_dir}/{db}")

        retry_count = 0
        retval = PRECONDITION_FAILURE
        while retry_count < 3 and retval == PRECONDITION_FAILURE:
          generation_id = _GetGenerationId(
              api, f"{gs_bucket}/{TOKEN_BUCKET}/{HISTORICAL_DB}")
          api.gsutil.download_url(
              f"{gs_bucket}/{TOKEN_BUCKET}/{HISTORICAL_DB}",
              temp_historical_db,
          )

          pw_cmd = [
              "vpython3",
              "-vpython-spec",
              vpython_spec,
              pw_tokenizer,
              "add",
              "--database",
              temp_historical_db,
              *local_unified_dbs,
          ]

          api.step("Merge token database", pw_cmd)

          pw_report = [
              "vpython3",
              "-vpython-spec",
              vpython_spec,
              pw_tokenizer,
              "report",
              temp_historical_db,
          ]

          api.step("Token database report", pw_report)
          cp_flags = [f"--if-generation-match={generation_id}"]
          if not api.build_menu.is_staging:
            cp_flags.append("--predefined-acl=publicRead")

          retval = api.gcloud.storage_cp(
              temp_historical_db,
              f"{gs_bucket}/{TOKEN_BUCKET}/{HISTORICAL_DB}",
              flags=cp_flags,
              ok_ret=(0, PRECONDITION_FAILURE),
          ).retcode
          retry_count += 1
          if retval == PRECONDITION_FAILURE:
            api.time.sleep(1)

        if retval == PRECONDITION_FAILURE and retry_count == 3:
          raise StepFailure(
              f"Failed to update {gs_bucket}/{TOKEN_BUCKET}/{HISTORICAL_DB}")

        CopyVersionedDatabase(
            api,
            temp_historical_db,
            gs_bucket,
            gob_config=gob_config,
        )


def GenTests(api):
  ARTIFACTS = """{
  "artifacts": {
    "artifacts": [
      {
        "artifactType": 31,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifactsd33fvz7t/firmware_metadata.jsonpb"
          }
        ]
      },
      {
        "artifactType": 30,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifactsd33fvz7t/myst.firmware.tbz2"
          }
        ]
      },
      {
        "artifactType": 55,
        "location": 2,
        "paths": [
          {
            "location": 2,
            "path": "[CLEANUP]/artifactsd33fvz7t/tokens.bin"
          }
        ]
      }
    ]
  }
}"""
  GSUTIL_STAT = """gs://chromeos-localmirror/distfiles/cros_ec/historical.bin:
      Creation time:          Mon, 11 Dec 2023 18:12:19 GMT
      Storage class:          MULTI_REGIONAL
      Cache-Control:          private, max-age=0
      Content-Encoding:       identity
      Content-Length:         6287
      Content-Type:           application/octet-stream
      Metadata:
          goog-reserved-file-mtime:1702318332
      Hash (crc32c):          CwcRfw==
      Hash (md5):             DEf0wTsRrqcGPKUAiCzExg==
      ETag:                   0c47f4c13b11aea7063ca500882cc4c6
      Generation:             1702318339485920
      Metageneration:         1"""

  PW_REPORT = """{
  "[CLEANUP]/tmpdt9nln0e/token/historical.bin": {
    "": {
      "present_entries": 188,
      "present_size_bytes": 4767,
      "total_entries": 188,
      "total_size_bytes": 4767,
      "collisions": {}
    }
  }
}"""

  def test(name, *args, **kwargs):
    status = kwargs.pop("status", "SUCCESS")
    kwargs.setdefault("builder", "fw-ec-postsubmit")
    props = kwargs.pop("input_properties", {})
    props.setdefault("firmware_location", 1)
    if name != "missing-gob-host":
      props.setdefault("gob_host", "android")
    if name != "missing-gob-project":
      props.setdefault(
          "gob_project",
          "platform/vendor/google/firmware/desktop/ec-prebuilts",
      )
    if name != "missing-gob-branch":
      props.setdefault("gob_branch", "main")
    kwargs["input_properties"] = props
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args, status=status)

  sdk_pin_path = "src/platform/ti50/sdk-version"

  yield test(
      "missing-gob-host",
      input_properties={"firmware_location": 1},
      status="FAILURE",
  )

  yield test(
      "missing-gob-project",
      input_properties={
          "firmware_location": 1,
          "gob_host": "android"
      },
      status="FAILURE",
  )

  yield test(
      "missing-gob-branch",
      input_properties={
          "firmware_location":
              1,
          "gob_host":
              "android",
          "gob_project":
              ("platform/vendor/google/firmware/desktop/ec-prebuilts"),
      },
      status="FAILURE",
  )

  yield test(
      "upload-fail",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          retcode=1,
      ),
      status="INFRA_FAILURE",
  )

  yield test(
      "working-upload-fail",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          retcode=1,
      ),
      api.post_check(post_process.DoesNotRun, "schedule signing build"),
      input_properties=({
          "firmware_location": 1,
          "chromiumos_sdk_pin_file": sdk_pin_path,
      }),
      status="INFRA_FAILURE",
  )

  yield test(
      "Update-historical-token-database",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          ARTIFACTS,
      ),
      api.step_data("Update Historical Token Database.Merge token database",
                    retcode=0),
      api.step_data(
          "Update Historical Token Database.gsutil stat",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.Token database report",
          stdout=api.raw_io.output_text(PW_REPORT),
      ),
      api.post_process(
          post_process.StepCommandContains,
          "Update Historical Token Database.Generate versioned database name.upload ec-token prebuilts.git clone",
          [
              "https://android.googlesource.com/platform/vendor/google/firmware/desktop/ec-prebuilts"
          ],
      ),
      builder="fw-zephyr-informational",
      input_properties={
          "firmware_location": common_pb2.PLATFORM_ZEPHYR,
          "gob_host": "android",
          "gob_project":
              ("platform/vendor/google/firmware/desktop/ec-prebuilts"),
          "gob_branch": "main",
      },
  )

  yield test(
      "Update-historical-token-database-gsutil-stat-failure",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          ARTIFACTS,
      ),
      builder="fw-zephyr-informational",
      input_properties={"firmware_location": common_pb2.PLATFORM_ZEPHYR},
      status="FAILURE",
  )

  yield test(
      "Update-historical-token-database-failure",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          ARTIFACTS,
      ),
      api.step_data(
          "Update Historical Token Database.gsutil stat",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.gcloud storage cp",
          retcode=PRECONDITION_FAILURE,
      ),
      api.step_data(
          "Update Historical Token Database.gsutil stat (2)",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.gcloud storage cp (2)",
          retcode=PRECONDITION_FAILURE,
      ),
      api.step_data(
          "Update Historical Token Database.gsutil stat (3)",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.gcloud storage cp (3)",
          retcode=PRECONDITION_FAILURE,
      ),
      builder="fw-zephyr-informational",
      input_properties={"firmware_location": common_pb2.PLATFORM_ZEPHYR},
      status="FAILURE",
  )

  yield test(
      "Update-historical-token-database-no-diff",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          ARTIFACTS,
      ),
      api.step_data("Update Historical Token Database.Merge token database",
                    retcode=0),
      api.step_data(
          "Update Historical Token Database.gsutil stat",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.Token database report",
          stdout=api.raw_io.output_text(PW_REPORT),
      ),
      api.step_data(
          "Update Historical Token Database.Generate versioned database name.upload ec-token prebuilts.git status",
          stdout=api.raw_io.output(""),
      ),
      builder="fw-zephyr-informational",
      input_properties={"firmware_location": common_pb2.PLATFORM_ZEPHYR},
  )

  yield test(
      "Update-historical-token-database-staging",
      api.cros_build_api.set_api_return(
          "upload artifacts",
          "FirmwareService/BundleFirmwareArtifacts",
          ARTIFACTS,
      ),
      api.step_data("Update Historical Token Database.Merge token database",
                    retcode=0),
      api.step_data(
          "Update Historical Token Database.gsutil stat",
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          "Update Historical Token Database.Token database report",
          stdout=api.raw_io.output_text(PW_REPORT),
      ),
      builder="fw-zephyr-informational",
      bucket="staging",
      input_properties={"firmware_location": common_pb2.PLATFORM_ZEPHYR},
  )
