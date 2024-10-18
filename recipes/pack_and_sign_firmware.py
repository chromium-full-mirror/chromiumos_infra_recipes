# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Pack and sign standalone firmware shellball."""

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos import common as common_pb2
from PB.chromiumos import signing as signing_pb2
from PB.chromite.api.image import SignImageResponse
from PB.recipe_modules.chromeos.signing.signing import SigningProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_release',
    'cros_source',
    'git',
    'signing',
    'src_state',
]


def RunSteps(api: RecipeApi):
  with api.cros_source.checkout_overlays_context():
    api.cros_source.configure_builder(api.buildbucket.gitiles_commit)
    api.cros_source.ensure_synced_cache()
    fw_config_path = api.src_state.workspace_path / 'firmware-config'
    with api.step.nest('clone firmware-config'):
      api.git.clone(
          'https://chrome-internal.googlesource.com/chromeos/firmware-config',
          target_path=fw_config_path, depth=1)

    with api.step.nest('pack firmware') as pres:
      # Ensure cipd packages are present.
      fw_path = api.src_state.workspace_path / 'src/platform/firmware'
      cipd_path = api.path.start_dir / 'cipd'
      api.cipd.ensure(cipd_path, fw_path / 'cipd_manifest.txt',
                      'ensure cipd packages for packing firmware')

      # Call pack_firmware with cipd bins in PATH.
      with api.context(env={
          'PATH': api.path.pathsep.join([str(cipd_path / 'bin'), '%(PATH)s'])
      }):
        # Pack firmware uses config for the base target. Remove prefix if present.
        base_target_name = api.build_menu.build_target.name.split(
            'android-')[-1]
        output_artifact_dir = api.path.mkdtemp('shellball-dir')
        output_artifact_name = api.cros_artifacts.artifacts_by_image_type.get(
            common_pb2.IMAGE_TYPE_SHELLBALL, 'chromeos-firmwareupdate')

        pack_fw_cmd = [
            'vpython3',
            fw_path / 'pack_firmware.py',
            '--imagedir',
            'tmp/distfiles',
            '--config',
            fw_config_path / base_target_name,
            '--output',
            output_artifact_dir / output_artifact_name,
            '--textproto',
            '--download',
        ]
        api.step('call pack_firmware', pack_fw_cmd)

    # Sign shellball.
    api.cros_release.validate_sign_types()
    # TODO(b/351853211): Ensure version is correct based on branch or config.
    with api.step.nest('sign firmware shellball') as pres:
      signed_build_list = api.signing.sign_artifacts(
          sign_types=[common_pb2.IMAGE_TYPE_SHELLBALL],
          channels=api.cros_release.channels, include_paygen=False,
          local_artifact_dir=output_artifact_dir, upload_unsigned=False)
      pres.logs['signed builds'] = str(signed_build_list)


# Sample SignImageResponse for testing.
sample_response = SignImageResponse(
    output_archive_dir='/archive_dir/',
    signed_artifacts=signing_pb2.BuildTargetSignedArtifacts(archive_artifacts=[
        signing_pb2.ArchiveArtifacts(
            build_target='android-kukui',
            channel=common_pb2.CHANNEL_CANARY,
            image_type=common_pb2.IMAGE_TYPE_SHELLBALL,
            signed_artifacts=[
                signing_pb2.SignedArtifact(
                    signed_artifact_name='signed_firmware.sh',
                ),
            ],
            signing_status=build_report_pb2.BuildReport.SignedBuildMetadata
            .SIGNING_STATUS_PASSED,
        )
    ]))


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'success',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'channels': [common_pb2.CHANNEL_CANARY],
              },
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='signed-firmware'))
          }),
      api.cros_build_api.set_api_return(
          'sign firmware shellball.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response)),
      api.post_check(
          post_process.DoesNotRun,
          'sign firmware shellball.sign artifacts.upload unsigned artifacts to '
          'signed-firmware bucket.upload unsigned artifacts for CHANNEL_CANARY'
      ), api.post_check(post_process.MustRun, 'pack firmware'),
      api.post_check(
          post_process.MustRun,
          'sign firmware shellball.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY'),
      api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='firmware-packager-android-kukui-main')

  yield api.build_menu.test(
      'use-dev-keys',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'channels': [common_pb2.CHANNEL_CANARY],
              },
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='signed-firmware',
                                        use_dev_keys=True)),
          }),
      api.post_check(
          post_process.LogContains,
          'sign firmware shellball.sign artifacts.call BAPI.call chromite.api.'
          'ImageService/SignImage', 'request',
          ['\"keyset\": \"DevPreMPKeys\"']),
      api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='firmware-packager-android-kukui-main')
