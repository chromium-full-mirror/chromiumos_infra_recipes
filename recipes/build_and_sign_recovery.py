# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build and sign recovery kernel images."""

import re

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos import common as common_pb2
from PB.chromiumos import signing as signing_pb2
from PB.chromite.api.image import SignImageResponse
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.signing.signing import SigningProperties

from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'cros_release',
    'cros_source',
    'gerrit',
    'git',
    'mutable_output',
    'signing',
    'src_state',
]

TEST_SIGNING_CONFIG = '''build_target_signing_configs {
      build_target: "kukui"
      keyset: "kukui-premp"
      signing_configs {
        image_type: IMAGE_TYPE_RECOVERY_KERNEL
      }
    }'''

CL_REVIEWERS = [
    'dabros@google.com', 'konrada@google.com', 'bernacki@google.com'
]


def create_or_update_symlink(api: RecipeApi, directory: Path, file: str,
                             symlink: str):
  with api.context(cwd=directory):
    if api.path.exists(directory / symlink):
      api.file.remove('remove existing symlink', directory / symlink)
    api.step('create symlink', ['ln', '-s', file, symlink])


def upload_recovery_prebuilts(api: RecipeTestApi, checkout: Path,
                              unsigned_recovery_path: Path,
                              signed_recovery_path: Path, target: str,
                              keyset_is_mp: bool,
                              abandon: bool = True) -> result_pb2.RawResult:
  """Uploads the recovery kernel prebuilts to the android repo."""
  # TODO(b/371248376): Once we no longer have the checkout, we'll need to create
  # it ourselves.
  # checkout = api.path.mkdtemp()
  with api.context(cwd=checkout):
    # TODO(b/371248376): Once we no longer have the checkout, we'll need to do a
    # new clone.
    # api.git.clone(
    #     f'https://googleplex-android.googlesource.com/device/google/desktop/{target}-kernels/6.6',
    #     depth=1)

    # Get the version. Filename is in the format `chromeos_[version]_[etc.]` so
    # parse out that version.
    version_match = re.search(r'chromeos_(\d+\.\d+\.\d+)_',
                              str(signed_recovery_path))
    if version_match:
      version = version_match.group(1)
    else:
      return result_pb2.RawResult(
          summary_markdown='Could not parse version from recovery image name.',
          status=bb_common_pb2.FAILURE,
      )

    # Copy the prebuild into the kernel prebuild repo.
    api.file.ensure_directory('make sure dev-signed exists',
                              api.path.join(checkout, 'recovery', 'dev-signed'))
    api.file.copy(
        'copy recovery kernel image to repo', unsigned_recovery_path,
        api.path.join(checkout, 'recovery', 'dev-signed',
                      f'vmlinuz_{version}.image'))
    create_or_update_symlink(api, checkout / 'recovery/dev-signed',
                             f'vmlinuz_{version}.image', 'vmlinuz_LATEST.image')
    directory = 'mp-signed' if keyset_is_mp else 'premp-signed'
    api.file.ensure_directory(f'make sure {directory} exists',
                              api.path.join(checkout, 'recovery', directory))
    api.file.copy(
        'copy recovery kernel image to repo', signed_recovery_path,
        api.path.join(checkout, 'recovery', directory,
                      f'vmlinuz_{version}.image'))
    create_or_update_symlink(api, checkout / f'recovery/{directory}',
                             f'vmlinuz_{version}.image', 'vmlinuz_LATEST.image')

    # Check to make sure there was actually a change.
    diff_lines = api.git.get_working_dir_diff_files()
    if not diff_lines:
      return result_pb2.RawResult(
          summary_markdown='No recovery kernel images changed.',
          status=bb_common_pb2.SUCCESS,
      )
    # Skip upload in CQ.
    if api.cv.active:
      api.step.empty('Skipping CL upload in CQ')
      return result_pb2.RawResult(
          status=bb_common_pb2.SUCCESS,
      )
    # Create a cl updating the file.
    api.git.add_all()
    bbid = api.buildbucket.build_url()
    commit_lines = [
        f'recovery-kernel: Update prebuilts to version {version}',
        '',
        f'Generated by {bbid}.',
        '',
        'Flag: build.RELEASE_RECOVERY_KERNEL_{target.upper()}_VERSION',
    ]
    api.git.commit('\n'.join(commit_lines))
    change = api.gerrit.create_change(
        f'/device/google/desktop/{target}-kernels/6.6',
        ref=api.git.get_branch_ref('main'), project_path=checkout,
        reviewers=CL_REVIEWERS if not api.cros_infra_config.is_staging else [],
        non_repo_checkout=True)
    if abandon:
      api.gerrit.abandon_change(change)
    return result_pb2.RawResult(
        summary_markdown=f'Updated recovery kernel prebuilts for {target}',
        status=bb_common_pb2.SUCCESS,
    )


def get_recovery_path(api: RecipeApi, response: SignImageResponse) -> Path:
  local_artifact_dir = response.output_archive_dir
  [only_artifact] = response.signed_artifacts.archive_artifacts
  [only_signed] = only_artifact.signed_artifacts

  return api.path.join(local_artifact_dir, only_signed.signed_artifact_name)


def get_keyset_is_mp(response: SignImageResponse) -> bool:
  [only_artifact] = response.signed_artifacts.archive_artifacts
  return only_artifact.keyset_is_mp


def RunSteps(api: RecipeApi):
  with api.mutable_output.wrap():
    with api.cros_source.checkout_overlays_context():
      api.cros_source.configure_builder(api.buildbucket.gitiles_commit)
      api.cros_source.ensure_synced_cache()

      # TODO(b/352625756): Remove prefix handling after consolidating config
      # with base targets.
      # Signing uses config for the base target. Remove prefix if present.
      target = api.build_menu.build_target.name.split('android-')[-1]

      # TODO(b/371248376): Remove when we can create our own recovery image.
      # For now, just get the image from the android prebuild repo.
      checkout = api.path.mkdtemp()
      with api.context(cwd=checkout):
        api.git.clone(
            f'https://googleplex-android.googlesource.com/device/google/desktop/{target}-kernels/6.6',
            depth=1)

        recovery_dir = api.path.mkdtemp(prefix='recovery')
        recovery_local_path = api.path.join(recovery_dir, 'vmlinuz.image')

        # copy the file in.
        api.file.copy('copy prebuild recovery image into temp dir',
                      api.path.join(checkout, 'recovery', 'vmlinuz.image'),
                      recovery_local_path)

      # In staging, allow cherry picking chromite CLs for testing.
      chromite_path = api.src_state.workspace_path / 'chromite'
      if api.cros_infra_config.is_staging:
        with api.step.nest('apply gerrit changes') as pres, api.context(
            cwd=chromite_path):
          relevant_changes = [
              x for x in api.buildbucket.build.input.gerrit_changes
              if x.project == 'chromiumos/chromite'
          ]
          if relevant_changes:
            patch_sets = api.gerrit.fetch_patch_sets(relevant_changes)
            for patch_set in patch_sets:
              commit_id = api.git.fetch_ref(patch_set.git_fetch_url,
                                            patch_set.git_fetch_ref)
              api.git.cherry_pick(commit_id)
          else:
            pres.step_text = 'No chromiumos/chromite changes to apply.'

      # Sign recovery kernel image and upload to GS.
      if api._test_data.enabled:  # pylint: disable=protected-access
        api.signing.test_api.signing_config_test_data = api._test_data.get(  # pylint: disable=protected-access
            'signing_config', TEST_SIGNING_CONFIG)
      api.cros_release.validate_sign_types()
      with api.step.nest('sign recovery kernel image') as pres:
        signed_image_response = api.signing.sign_artifacts(
            sign_types=[common_pb2.IMAGE_TYPE_RECOVERY_KERNEL],
            channels=api.cros_release.channels, include_paygen=False,
            local_artifact_dir=recovery_dir, upload_unsigned=False)
        if not signed_image_response:
          raise StepFailure('Empty signing config for build target')
        signed_recovery_path = get_recovery_path(api, signed_image_response)
        pres.logs['signed builds'] = signed_recovery_path

      # Open a cl with the new recovery kernel prebuilts.
      return upload_recovery_prebuilts(api, checkout, recovery_local_path,
                                       signed_recovery_path, target,
                                       get_keyset_is_mp(signed_image_response),
                                       abandon=api.cros_infra_config.is_staging)


# Sample SignImageResponse for testing.
def sample_response(
    name: str = 'chromeos_16110.0.0_android-kukui-channel_DevPreMPKeys'
) -> SignImageResponse:
  return SignImageResponse(
      output_archive_dir='/archive_dir/',
      signed_artifacts=signing_pb2.BuildTargetSignedArtifacts(
          archive_artifacts=[
              signing_pb2.ArchiveArtifacts(
                  build_target='android-kukui',
                  channel=common_pb2.CHANNEL_CANARY,
                  image_type=common_pb2.IMAGE_TYPE_RECOVERY_KERNEL,
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name=name,
                      ),
                  ],
                  signing_status=build_report_pb2.BuildReport
                  .SignedBuildMetadata.SIGNING_STATUS_PASSED,
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
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response())),
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.ImageService/SignImage.write input file',
          [re.compile('.*"imageType": 21.*')]),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'
          'gsutil cp', [
              'gs://signed-firmware/canary-channel/kukui/1234.56.0/',
          ]),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.DoesNotRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='recovery-android-kukui-main',
  )

  yield api.build_menu.test(
      'symlink-exists',
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
      api.path.exists(
          api.path.cleanup_dir /
          'tmp_tmp_1/recovery/dev-signed/vmlinuz_LATEST.image',
          api.path.cleanup_dir /
          'tmp_tmp_1/recovery/premp-signed/vmlinuz_LATEST.image'),
      api.cros_build_api.set_api_return(
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response())),
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.ImageService/SignImage.write input file',
          [re.compile('.*"imageType": 21.*')]),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'
          'gsutil cp', [
              'gs://signed-firmware/canary-channel/kukui/1234.56.0/',
          ]),
      api.post_check(post_process.MustRun, 'remove existing symlink'),
      api.post_check(post_process.MustRun, 'create symlink'),
      api.post_check(post_process.MustRun, 'remove existing symlink (2)'),
      api.post_check(post_process.MustRun, 'create symlink (2)'),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.DoesNotRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='recovery-android-kukui-main',
  )

  yield api.build_menu.test(
      'signing-skipped',
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
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.recipe_test_data(signing_config="""build_target_signing_configs {
  build_target: "kukui"
}"""),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.DoesNotRun,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='recovery-android-kukui-main',
      status='FAILURE',
  )

  yield api.build_menu.test(
      'no-diff',
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
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response())),
      api.step_data('git status', stdout=api.raw_io.output('')),
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.ImageService/SignImage.write input file',
          [re.compile('.*"imageType": 21.*')]),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'
          'gsutil cp', [
              'gs://signed-firmware/canary-channel/kukui/1234.56.0/',
          ]),
      api.post_check(post_process.SummaryMarkdown,
                     'No recovery kernel images changed.'),
      api.post_check(post_process.DoesNotRun, 'git commit'),
      api.post_check(post_process.DoesNotRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='recovery-android-kukui-main',
  )

  yield api.build_menu.test(
      'invalid-version-in-name',
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
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage',
          MessageToJson(sample_response(name='lalala_no-version_present'))),
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.ImageService/SignImage.write input file',
          [re.compile('.*"imageType": 21.*')]),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'
          'gsutil cp', [
              'gs://signed-firmware/canary-channel/kukui/1234.56.0/',
          ]),
      api.post_check(post_process.SummaryMarkdown,
                     'Could not parse version from recovery image name.'),
      api.post_check(post_process.DoesNotRun, 'git commit'),
      api.post_check(post_process.DoesNotRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='recovery-android-kukui-main',
      status='FAILURE',
  )

  yield api.build_menu.test(
      'staging',
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
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response())),
      api.post_process(post_process.StepCommandContains, 'git clone', [
          'https://googleplex-android.googlesource.com/device/google/desktop/kukui-kernels/6.6'
      ]),
      api.post_check(post_process.MustRun,
                     'copy prebuild recovery image into temp dir'),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.ImageService/SignImage.write input file',
          [re.compile('.*"imageType": 21.*')]),
      api.post_check(
          post_process.StepCommandContains,
          'sign recovery kernel image.sign artifacts.upload signed artifacts to '
          'signed-firmware bucket.upload signed artifacts for CHANNEL_CANARY.'
          'gsutil cp', [
              'gs://signed-firmware/canary-channel/kukui/1234.56.0/',
          ]),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.MustRun, 'abandon CL 1'),
      # Omit reviewers in staging.
      api.post_check(
          post_process.StepCommandDoesNotContain,
          'create gerrit change for /device/google/desktop/kukui-kernels/6.6.git_cl upload',
          '--reviewers'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      bucket='staging',
      builder='recovery-android-kukui-main',
  )

  test_gerrit_changes = [
      bb_common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                 change=1, project='chromiumos/chromite',
                                 patchset=1),
      bb_common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                 change=2, project='some-other-project',
                                 patchset=1),
  ]
  fetch_changes_response = {
      101: {
          'change_id': '101',
          'revision_info': {
              'commit': {
                  'message': 'test commit',
              },
          },
      }
  }
  yield api.build_menu.test(
      'cq',
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
      api.gerrit.set_gerrit_fetch_changes_response('apply gerrit changes',
                                                   test_gerrit_changes,
                                                   fetch_changes_response),
      # Only cherry pick the chromite change.
      api.post_check(post_process.MustRun,
                     'apply gerrit changes.git cherry-pick'),
      api.post_check(post_process.DoesNotRun,
                     'apply gerrit changes.git cherry-pick (2)'),
      api.cros_build_api.set_api_return(
          'sign recovery kernel image.sign artifacts.call BAPI',
          'ImageService/SignImage', MessageToJson(sample_response())),
      api.post_check(
          post_process.LogContains,
          'sign recovery kernel image.sign artifacts.call BAPI.call chromite.api.'
          'ImageService/SignImage', 'request',
          ['\"keyset\": \"DevPreMPKeys\"']),
      # Skip CL upload.
      api.post_check(post_process.DoesNotRun, 'git commit'),
      api.post_check(post_process.MustRun, 'Skipping CL upload in CQ'),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      bucket='staging',
      builder='recovery-android-kukui-main',
      cq=True,
      gerrit_changes=test_gerrit_changes,
  )
