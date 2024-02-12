# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that manages Zephyr EC firmware's historical token database.

This recipe builds firmware and merges its unified database with the
historical database in GCS. This database maintenance runs on a
24 hour cadence.
"""

import re

from PB.chromite.api.firmware import BuildAllFirmwareRequest
import PB.chromiumos.common as common_pb2
from PB.recipes.chromeos.build_firmware_historical_db import BuildFirmwareHistoricalDbProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'failures',
    'gcloud',
    'src_state',
    'test_util',
]


PROPERTIES = BuildFirmwareHistoricalDbProperties
PRECONDITION_FAILURE = 412
HISTORICAL_DB = 'historical.bin'
TOKEN_BUCKET = 'gs://chromeos-localmirror/cros_ec/tokens'
TOKEN_VERSION_BUCKET = f'{TOKEN_BUCKET}/version'

def RunSteps(api, properties):
  with api.build_menu.configure_builder(
  ) as config, api.build_menu.setup_workspace():
    api.build_menu.setup_chroot()

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
        name='build firmware',
    )

    snapshot_sha = api.src_state.gitiles_commit.id
    api.easy.set_properties_step(got_revision=snapshot_sha,
                                 step_name='output got_revision')

    uploaded_artifacts, _ = api.build_menu.upload_artifacts(
        config=config,
        report_to_spike=api.cros_infra_config.config.artifacts
        .attestation_eligible,
    )

    UpdateHistoricalTokenDatabase(api, location, uploaded_artifacts)


def _GetStatInfo(api: RecipeApi, gsFile: str, field: str):

  def _GetField(name, output):
    m = re.search(r'%s:\s*(.+)' % re.escape(name), output.stdout)
    if m:
      return m.group(1)
    raise StepFailure('Field "%s" missing in "%s"' % (name, output.stdout))

  statOut = api.gsutil.stat(
      gsFile,
      stdout=api.raw_io.output_text(),
  )

  return _GetField(field, statOut)


def _GetGenerationId(api: RecipeApi, gsFile: str):
  return int(_GetStatInfo(api, gsFile, 'Generation'))


def CopyVersionedDatabase(api: RecipeApi, source: str):
  with api.step.nest('Generate versioned database name'):
    file_hash = api.file.file_hash(source, test_data='deadbeef')
    versionedFileName = f'historical.{file_hash}.bin'
    api.gcloud.storage_cp(
        source,
        f'{TOKEN_VERSION_BUCKET}/{versionedFileName}',
        flags=[
            '--if-generation-match=0',
            '--predefined-acl=publicRead',
        ],
        ok_ret=(0, PRECONDITION_FAILURE),
    )


def UpdateHistoricalTokenDatabase(
    api: RecipeApi,
    location: common_pb2.FwLocation,
    uploaded_artifacts: UploadedArtifacts,
):
  """Updates Historical Token Database in GCS

  Updates the historical database in GCS using preconditions
  to avoid any race conditions between other builders.

  Args:
    api: RecipesAPI object for dependencies.
    location: The firmware location.
    builder_name: Name of builder.
    uploaded_artifacts: Artifacts uploaded.
  """
  if location == common_pb2.PLATFORM_ZEPHYR:
    cros_src_path = api.cros_source.workspace_path
    pw_tokenizer = cros_src_path.join(
        'src/third_party/pigweed/pw_tokenizer/py/pw_tokenizer/database.py')

    with api.step.nest('Update Historical Token Database'):
      if 'FIRMWARE_TOKEN_DATABASE' in uploaded_artifacts.files_by_artifact:
        temp_dir = api.path.mkdtemp()
        token_dir = api.path.join(temp_dir, 'token')
        api.file.ensure_directory('Create token download directory', token_dir)
        temp_historical_db = api.path.join(token_dir, HISTORICAL_DB)

        unified_dbs = uploaded_artifacts.files_by_artifact[
            'FIRMWARE_TOKEN_DATABASE']

        local_unified_dbs = []
        for db in unified_dbs:
          api.gsutil.download(
              uploaded_artifacts.gs_bucket,
              f'{uploaded_artifacts.gs_path}/{db}',
              f'{token_dir}/{db}',
          )
          local_unified_dbs.append(f'{token_dir}/{db}')

        retry_count = 0
        retval = PRECONDITION_FAILURE
        while retry_count < 3 and retval == PRECONDITION_FAILURE:
          generation_id = _GetGenerationId(api,
                                           f'{TOKEN_BUCKET}/{HISTORICAL_DB}')
          api.gsutil.download_url(f'{TOKEN_BUCKET}/{HISTORICAL_DB}',
                                  temp_historical_db)

          pw_cmd = [
              'vpython3',
              pw_tokenizer,
              'add',
              '--database',
              temp_historical_db,
              *local_unified_dbs,
          ]

          api.step('Merge token database', pw_cmd)

          pw_report = [
              'vpython3',
              pw_tokenizer,
              'report',
              temp_historical_db,
          ]

          api.step('Token database report', pw_report)

          retval = api.gcloud.storage_cp(
              temp_historical_db,
              f'{TOKEN_BUCKET}/{HISTORICAL_DB}',
              flags=[
                  f'--if-generation-match={generation_id}',
                  '--predefined-acl=publicRead',
              ],
              ok_ret=(0, PRECONDITION_FAILURE),
          ).retcode
          retry_count += 1
          if retval == PRECONDITION_FAILURE:
            api.time.sleep(1)

        if retval == PRECONDITION_FAILURE and retry_count == 3:
          raise StepFailure(f'Failed to update {TOKEN_BUCKET}/{HISTORICAL_DB}')

        CopyVersionedDatabase(api, temp_historical_db)


def GenTests(api):
  ARTIFACTS = '''{
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
}'''
  GSUTIL_STAT = '''gs://chromeos-localmirror/cros_ec/historical.bin:
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
      Metageneration:         1'''

  PW_REPORT = '''{
  "[CLEANUP]/tmpdt9nln0e/token/historical.bin": {
    "": {
      "present_entries": 188,
      "present_size_bytes": 4767,
      "total_entries": 188,
      "total_size_bytes": 4767,
      "collisions": {}
    }
  }
}'''

  def test(name, *args, **kwargs):
    status = kwargs.pop('status', 'SUCCESS')
    kwargs.setdefault('builder', 'fw-ec-postsubmit')
    kwargs.setdefault('input_properties', {'firmware_location': 1})
    build = api.test_util.test_child_build(None, **kwargs).build
    return api.test(name, build, *args, status=status)

  sdk_pin_path = 'src/platform/ti50/sdk-version'

  yield test(
      'upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts',
          retcode=1,
      ),
      status='INFRA_FAILURE',
  )

  yield test(
      'working-upload-fail',
      api.cros_build_api.set_api_return(
          'upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts',
          retcode=1,
      ),
      api.post_check(post_process.DoesNotRun, 'schedule signing build'),
      input_properties=({
          'firmware_location': 1,
          'chromiumos_sdk_pin_file': sdk_pin_path,
      }),
      status='INFRA_FAILURE',
  )

  yield test(
      'Update-historical-token-database',
      api.cros_build_api.set_api_return(
          'upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts',
          ARTIFACTS,
      ),
      api.step_data('Update Historical Token Database.Merge token database',
                    retcode=0),
      api.step_data(
          'Update Historical Token Database.gsutil stat',
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          'Update Historical Token Database.Token database report',
          stdout=api.raw_io.output_text(PW_REPORT),
      ),
      builder='fw-zephyr-informational',
      input_properties={'firmware_location': common_pb2.PLATFORM_ZEPHYR},
  )

  yield test(
      'Update-historical-token-database-gsutil-stat-failure',
      api.cros_build_api.set_api_return(
          'upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts',
          ARTIFACTS,
      ),
      builder='fw-zephyr-informational',
      input_properties={'firmware_location': common_pb2.PLATFORM_ZEPHYR},
      status='FAILURE',
  )

  yield test(
      'Update-historical-token-database-failure',
      api.cros_build_api.set_api_return(
          'upload artifacts',
          'FirmwareService/BundleFirmwareArtifacts',
          ARTIFACTS,
      ),
      api.step_data(
          'Update Historical Token Database.gsutil stat',
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          'Update Historical Token Database.gcloud storage cp',
          retcode=PRECONDITION_FAILURE,
      ),
      api.step_data(
          'Update Historical Token Database.gsutil stat (2)',
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          'Update Historical Token Database.gcloud storage cp (2)',
          retcode=PRECONDITION_FAILURE,
      ),
      api.step_data(
          'Update Historical Token Database.gsutil stat (3)',
          stdout=api.raw_io.output_text(GSUTIL_STAT),
      ),
      api.step_data(
          'Update Historical Token Database.gcloud storage cp (3)',
          retcode=PRECONDITION_FAILURE,
      ),
      builder='fw-zephyr-informational',
      input_properties={'firmware_location': common_pb2.PLATFORM_ZEPHYR},
      status='FAILURE',
  )
