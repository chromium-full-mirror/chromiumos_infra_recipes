# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related operations (e.g. paygen, signing)."""
import json

from google.protobuf import json_format

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.chromiumos.common import (Channel, IMAGE_TYPE_RECOVERY,
                                  IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
                                  IMAGE_TYPE_ACCESSORY_USBPD,
                                  IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_GSC_FIRMWARE)
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class CrosReleaseApi(recipe_api.RecipeApi):

  @property
  def manifest_versions_url(self):
    """Returns the git repo URL for manifest versions."""
    return 'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  @property
  def _supported_sign_types(self):
    """Supported image types for signing.

    These are kept in sync with chromite/scripts/pushimage.py.

    Returns:
      A set of image type enum values.
    """
    return set([
        IMAGE_TYPE_RECOVERY, IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
        IMAGE_TYPE_ACCESSORY_USBPD, IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
        IMAGE_TYPE_GSC_FIRMWARE
    ])

  def validate_sign_types(self, sign_types):
    """Takes an array of IMAGE_TYPE enums and validates them or raises StepFailure."""
    if not set(sign_types).issubset(self._supported_sign_types):
      raise StepFailure('attempting to sign type not in supported sign types')

  def __init__(self, properties, **kwargs):
    super(CrosReleaseApi, self).__init__(**kwargs)
    self._release_bucket = properties.release_bucket
    self._src_paygen_bucket = properties.src_paygen_bucket
    self._channels = properties.channels
    self._sign_types = properties.sign_types
    self._dryrun = properties.dryrun
    self._paygen_dryrun = properties.paygen_dryrun
    self._releasespec = None
    self._dont_upload_to_manifest_versions = properties.dont_upload_to_manifest_versions

  @property
  def releasespec(self):
    """Return the releasespec as created by this module, or None."""
    return self._releasespec

  def create_releasespec(self, specs_dir='buildspecs', branch='release',
                         step_name='create releasespec', dry_run=False,
                         gs_location=None):
    """Create a pinned manifest and upload to manifest-versions/releasespecs.

    Args:
      specs_dir (str): Relative path in manifest-versions in which to place the
        pinned manifest.
      branch (str): The branch of manifest-versions that will be used, or None
        to use the default branch.
      step_name (str): The step name to use.
      dry_run (bool): Whether the git push is --dry-run.
      gs_location (string): If set, will also upload the pinned manifest to GS.

    Returns:
      Full URL path to newly-uploaded manifest.
    """
    with self.m.step.nest(step_name):
      with self.m.context(cwd=self.m.src_state.workspace_path):
        manifest_data = self.m.repo.manifest(step_name='create pinned manifest',
                                             pinned=True)

      manifest_versions_checkout = self.m.path.mkdtemp(
          prefix='manifest-versions')
      with self.m.context(cwd=manifest_versions_checkout):
        # Clone manifest-versions repo to current path.
        with self.m.step.nest('clone manifest-versions'):
          self.m.git.clone(self.manifest_versions_url, branch=branch,
                           single_branch=True, depth=1)
          branch = branch or self.m.git.current_branch()

        version = self.m.cros_version.version
        manifest_file = self.m.path.join(specs_dir, version.buildspec_filename)
        manifest_path = self.m.path.join(manifest_versions_checkout,
                                         manifest_file)
        manifest_dir = self.m.path.dirname(manifest_path)
        self.m.file.ensure_directory('ensure {} exists'.format(manifest_dir),
                                     manifest_dir)
        self.m.file.write_raw('write {}'.format(manifest_file), manifest_path,
                              manifest_data)

        with self.m.step.nest('commit buildspec') as presentation:
          # Only commit file if it's changed. During active Rubik development,
          # (when Rubik doesn't increment CrOS version) a staging and production
          # build that run in rapid succession may not have any difference in
          # buildspec. In this case, `git add` and `git commit` will pass on
          # the second builder without actually doing anything, but `git push`
          # will fail with a 'no new changes' message.
          if not self.m.git.diff_check(manifest_path):
            presentation.step_text = 'no change since last commit'
          elif not self._dont_upload_to_manifest_versions:
            commit_lines = [
                'Add {}'.format(manifest_file),
                '',
                'Generated by Rubik.',
                '',
                'Cr-Build-Url: {}'.format(self.m.buildbucket.build_url()),
                'Cr-Automation-Id: cros_release/create_releasespec',
            ]
            commit_message = '\n'.join(commit_lines) + '\n'
            with self.m.step.nest('commit {} to {}'.format(
                manifest_file, branch)):
              self.m.git.add([manifest_file])
              self.m.git.commit(commit_message)
              if not dry_run:
                change = self.m.gerrit.create_change(
                    'chromeos/manifest-versions',
                    ref=self.m.git.get_branch_ref(branch),
                    project_path=manifest_versions_checkout)
                labels = {
                    self.m.gerrit.Label.BOT_COMMIT: 1,
                    self.m.gerrit.Label.VERIFIED: 1,
                }
                self.m.gerrit.set_change_labels_remote(change, labels)
                self.m.gerrit.submit_change(
                    change, project_path=manifest_versions_checkout)

        manifest_gs_path = ''
        if gs_location:
          if gs_location.startswith('gs://'):
            gs_location = gs_location[len('gs://'):]
          with self.m.step.nest('upload {} to gs://{}'.format(
              manifest_file, gs_location)):
            # Split bucket off, and then append buildspec to the rest of the path (if any).
            # If a filename is not supplied in gs_location, we use the buildspec_filename.
            gs_toks = self.m.path.dirname(gs_location).split("/", 1)
            gs_bucket = gs_toks[0]
            gs_path = gs_toks[1]
            if self.m.path.basename(gs_location) == "":
              gs_path = self.m.path.join(gs_path, version.buildspec_filename)
            self.m.gsutil.upload(manifest_path, gs_bucket, gs_path)
            manifest_gs_path = 'gs://{}/{}'.format(gs_bucket, gs_path)

      self._releasespec = ManifestLocation(
          manifest_repo_url=self.manifest_versions_url, branch=branch,
          manifest_file=manifest_file, manifest_gs_path=manifest_gs_path)

  def schedule_payload_generation(self):
    """Schedule the generation of release payloads using the context of a build.

    This is nonblocking, will launch and return the id for the paygen
    orchestrator. It assumes its being ran after a local build has been made.

    Args:
      build_target_name (str): The builder target name.
      target_chromeos_version (str): The target chromeos version (e.g. '13337.0.1').
      milestone (int): The milestone number.

    Returns:
      The int build id for the launched orchestrator.
    """
    pg_orch_builder = ('staging-paygen-orchestrator' if
                       self.m.build_menu.is_staging else 'paygen-orchestrator')
    bucket = 'staging' if self.m.build_menu.is_staging else 'release'

    version = self.m.cros_version.version
    with self.m.step.nest('generate payloads'):
      paygen_properties = {
          'builder_name': self.m.build_menu.build_target.name,
          'target_chromeos_version': version.platform_version,
          'delta_types': [],
          'channels': [Channel.Name(x) for x in self._channels],
          'au_testing_models': self.get_au_testing_models(),
          'au_fsi_testing_models': self.get_au_testing_models(fsi=True),
          'src_bucket': self._src_paygen_bucket or self._release_bucket,
          'dest_bucket': self._release_bucket,
          'dryrun': self._paygen_dryrun,
          'delta_payload_test_override': 'RESPECT_CONFIG',
          'full_payload_test_override': 'RESPECT_CONFIG',
      }
      request = self.m.buildbucket.schedule_request(
          builder=pg_orch_builder,
          bucket=bucket,
          properties=paygen_properties,
          can_outlive_parent=False,
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(self.m.buildbucket.build.id)),
      )
      builds = self.m.buildbucket.run(
          [request], timeout=self.m.cros_paygen.paygen_orchestrator_timeout_sec,
          step_name='running paygen orchestrator')

      paygen_orch_build = builds[0]
      if paygen_orch_build.status != common_pb2.SUCCESS:
        raise StepFailure('paygen orchestrator failed\n'
                          'https://cr-buildbucket.appspot.com/build/{}'.format(
                              paygen_orch_build.id))

      if 'payloads' in paygen_orch_build.output.properties:
        payload_information = paygen_orch_build.output.properties['payloads']
        payload_information = [
            json_format.Parse(payload, BuildReport.Payload())
            for payload in payload_information
        ]
        self.m.build_reporting.publish(
            BuildReport(payloads=payload_information))

      return builds

  def get_au_testing_models(self, fsi=False):
    """Determine which models are configured to run autoupdate tests.

    TODO(b/223252953): Filter down to models that are available in the lab.

    Args:
      fsi (bool): If True, then return all models which should run autoupdate
        tests for FSI images, which require broader testing than non-FSI.

    Returns:
      List[str]: The names of each model that should run paygen tests.
    """
    with self.m.step.nest('determine %s testing models' %
                          ('fsi' if fsi else 'au')):
      config = self.m.cros_test_plan.generate_target_test_requirements_config(
          paygen=True)
      if config is None:
        raise StepFailure('No response from generate_test_config')
      builder = self.m.buildbucket.build.builder.builder
      if builder not in config:
        raise StepFailure('Builder %s not found in paygen test config: %s' %
                          (builder, json.dumps(config)))
      model_config = config[builder]
      if fsi:
        return sorted(list(model_config.keys()))
      return sorted(
          [model for (model, suites) in model_config.items() if 'au' in suites])

  def _create_sentinel_file(self, path):
    """Create a sentinel file at the provided path.

    Args:
      path (str): path to generate the file at (including file name).
    """
    tempfile = self.m.path.mkstemp()
    self.m.file.write_text('write to temp file', tempfile, 'generated by rubik')
    self.m.gsutil(['cp', tempfile, path])

  def push_and_sign_images(self, config, sysroot):
    """Call the Push Image Build API endpoint for the build.

    This pushes the image files to the appropriate bucket and prepares them
    for signing. The actual execution of these procedures is handled in the
    underlying script, chromite/scripts/push_image.py. Must be used in the
    context of a build.

    Args:
      config (BuilderConfig): The Builder Config for the build.
      sysroot (Sysroot): sysroot to use.

    Return:
      Tuple of (gs_image_dir, instructions_uris):
        gs_image_dir is the GS directory the image was pushed from.
        instructions_uris is a list of URIs to instructions files for the
          pushed images.
    """
    with self.m.step.nest('push images') as presentation:
      gs_bucket = self.m.build_menu.config.artifacts.artifacts_gs_bucket

      # Use the publish dir because it's formatted the way that we want for
      # pushimage. Currently images are uploaded using the legacy artifacts
      # service so we'll pull from that. b/204435742 for context.
      gs_image_dir_template = 'gs://{gs_bucket}/{gs_path}'
      publish_template = self.m.cros_artifacts.gs_upload_path or '{gs_path}'
      output_artifacts = config.artifacts.artifacts_info.legacy.output_artifacts
      if output_artifacts and output_artifacts[0].gs_locations:
        publish_template = output_artifacts[0].gs_locations[0]
        # Publish templates include the bucket.
        gs_image_dir_template = 'gs://{gs_path}'
      gs_path = self.m.cros_artifacts.artifacts_gs_path(
          config.id.name, sysroot.build_target, config.id.type,
          template=publish_template)

      gs_image_dir = gs_image_dir_template.format(gs_bucket=gs_bucket,
                                                  gs_path=gs_path)
      presentation.links['gs image dir'] = (
          'https://console.cloud.google.com/storage/browser/{gs_path}'.format(
              gs_path=gs_image_dir[len('gs://'):]))
      sysroot = Sysroot(build_target=self.m.build_menu.build_target)
      # Validate sign types given.
      self.validate_sign_types(self._sign_types)

      # Emit release bucket for each channel.
      for channel in self._channels:
        channel_name = self.m.cros_release_util.channel_to_long_string(channel)
        gs_directory = '{bucket}/{channel}/{build_target}/{version}'.format(
            bucket=self._release_bucket, channel=channel_name,
            build_target=sysroot.build_target.name,
            version=str(self.m.cros_version.version.platform_version))
        presentation.links['gs release dir: %s' % Channel.Name(channel)] = (
            'https://console.cloud.google.com/storage/browser/%s' %
            gs_directory)
        # TODO(b/230518952): remove this when CPFE issue is resolved.
        self._create_sentinel_file(
            'gs://{}/BUILT_BY_RUBIK'.format(gs_directory))

      response = self.m.cros_artifacts.push_image(
          self.m.build_menu.chroot, gs_image_dir, sysroot,
          sign_types=self._sign_types,
          dest_bucket='gs://' + self._release_bucket, channels=self._channels)
      instructions_uris = [
          i.instructions_file_path for i in response.instructions
      ]

      return (gs_image_dir, instructions_uris)
