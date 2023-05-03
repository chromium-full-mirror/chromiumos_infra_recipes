# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related operations (e.g. paygen, signing)."""
import json

from google.protobuf import json_format

from recipe_engine import recipe_api
from recipe_engine.recipe_api import InfraFailure, StepFailure

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import (Channel, IMAGE_TYPE_RECOVERY,
                                  IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
                                  IMAGE_TYPE_ACCESSORY_USBPD,
                                  IMAGE_TYPE_HPS_FIRMWARE,
                                  IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_GSC_FIRMWARE)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from RECIPE_MODULES.chromeos.gerrit.api import Label


# Supported image types for signing.
# These are kept in sync with _SUPPORTED_IMAGE_TYPES in
# chromite/scripts/pushimage.py.
SUPPORTED_SIGN_TYPES = set([
    IMAGE_TYPE_RECOVERY, IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
    IMAGE_TYPE_ACCESSORY_USBPD, IMAGE_TYPE_HPS_FIRMWARE,
    IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE, IMAGE_TYPE_GSC_FIRMWARE
])

# GS URI to the Release Schedule.
RC_SCHEDULE_URI = 'gs://chromeos-release-schedule/schedule.json'
RELEASE_HIGH_PRIO_QS_ACCOUNT = 'release_high_prio'
RELEASE_MED_PRIO_QS_ACCOUNT = 'release_med_prio'
RELEASE_LOW_PRIO_QS_ACCOUNT = 'release_low_prio'


class CrosReleaseApi(recipe_api.RecipeApi):
  MANIFEST_VERSIONS_URL = \
      'https://chrome-internal.googlesource.com/chromeos/manifest-versions'

  def validate_sign_types(self, sign_types):
    """Checks whether an array of IMAGE_TYPE enums is valid for signing.

    Raises:
      StepFailure: If any of the given image types is not supported for signing.
    """
    if not set(sign_types).issubset(SUPPORTED_SIGN_TYPES):
      raise StepFailure('attempting to sign type not in supported sign types')

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._release_bucket = properties.release_bucket
    self._src_paygen_bucket = properties.src_paygen_bucket
    self._channels = properties.channels
    self._sign_types = properties.sign_types
    self._dryrun = properties.dryrun
    self._paygen_dryrun = properties.paygen_dryrun
    self._buildspec = None
    self._dont_upload_to_manifest_versions = properties.dont_upload_to_manifest_versions
    self._minios_unsupported = properties.minios_unsupported
    self._dynamic_qs_account = properties.dynamic_qs_account

  @property
  def buildspec(self):
    """Return the buildspec as created by this module, or None."""
    return self._buildspec

  @buildspec.setter
  def buildspec(self, buildspec: ManifestLocation):
    self._buildspec = buildspec

  def check_buildspec(self, fatal: bool = False):
    """Checks that the build was given a buildspec and that there doesn't
      already exist a build for this buildspec (and this build is not a retry).

    Args:
      fatal: Whether or not to kill the build if the build already ran.
    """
    with self.m.step.nest('check buildspec') as presentation:
      buildspec = self.m.cros_source.sync_to_manifest
      if not buildspec:
        raise StepFailure(
            'build was not given a buildspec (via `$chromeos/cros_source.syncToManifest`).'
        )

      if not self.m.checkpoint.is_retry():
        with self.m.step.nest('check for previous builds') as presentation:
          predicate = builds_service_pb2.BuildPredicate(
              builder=self.m.buildbucket.build.builder)
          # Default limit is 1000 builds so shouldn't have to worry about pagination.
          builds = self.m.buildbucket.search(predicate, limit=1000,
                                             fields=['id', 'input.properties'],
                                             timeout=300)
          for build in builds:
            # Don't want to look at ourselves which is necessarily a match.
            if build.id == self.m.buildbucket.build.id:
              continue
            bs = dict(
                dict(
                    dict(build.input.properties).get(
                        '$chromeos/cros_source',
                        {})).get('syncToManifest',
                                 {})).get('manifestGsPath', None)
            if bs == buildspec.manifest_gs_path:
              err = 'build {} already exists for buildspec {}. see go/cros-try for instructions on retrying.'.format(
                  build.id, bs)
              presentation.step_text = err
              presentation.status = self.m.step.FAILURE
              if fatal:
                raise StepFailure(err)

  def create_buildspec(self, specs_dir='buildspecs', branch='release',
                       step_name='create buildspec', dry_run=False,
                       gs_location=None):
    """Create a pinned manifest and upload to manifest-versions and/or GS.

    If the buildspec is uploaded to GS, this function also creates a public
    buildspec using Manifest Doctor.

    Args:
      specs_dir (str): Relative path in manifest-versions in which to place the
        pinned manifest.
      branch (str): The branch of manifest-versions that will be used, or None
        to use the default branch.
      step_name (str): The step name to use.
      dry_run (bool): Whether the git push is --dry-run.
      gs_location (string): If set, will also upload the pinned manifest to GS.
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
          self.m.git.clone(self.MANIFEST_VERSIONS_URL, branch=branch,
                           single_branch=True, depth=1)
          branch = branch or self.m.git.current_branch()

        version = self.m.cros_version.version
        buildspec_filename = version.buildspec_filename
        # If the build is a staging build, suffix the buildspec with the BBID to avoid
        # clobbering. See b/250670854 for context.
        if self.m.build_menu.is_staging:
          buildspec_filename = buildspec_filename.replace(
              '.xml', '-{}.xml'.format(self.m.buildbucket.build.id))
        manifest_file = self.m.path.join(specs_dir, buildspec_filename)
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
                # Formerly  'Cr-Automation-Id: cros_release/create_releasespec'
                'Cr-Automation-Id: cros_release/create_buildspec',
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
                    Label.BOT_COMMIT: 1,
                    Label.VERIFIED: 1,
                }
                self.m.gerrit.set_change_labels_remote(change, labels)
                self.m.gerrit.submit_change(
                    change, project_path=manifest_versions_checkout, retries=3)

        manifest_gs_path = ''
        if gs_location:
          if gs_location.startswith('gs://'):
            gs_location = gs_location[len('gs://'):]
          # Split bucket off, and then append buildspec to the rest of the path (if any).
          # If a filename is not supplied in gs_location, we use the buildspec_filename.
          gs_toks = self.m.path.dirname(gs_location).split("/", 1)
          gs_bucket = gs_toks[0]
          gs_path = self.m.path.join(
              gs_toks[1],
              self.m.path.basename(gs_location) or buildspec_filename)
          manifest_gs_path = 'gs://{}/{}'.format(gs_bucket, gs_path)
          with self.m.step.nest('upload {} to {}'.format(
              manifest_file, manifest_gs_path)):
            self.m.gsutil.upload(manifest_path, gs_bucket, gs_path)

          # Create the public buildspec immediately so it can be used by the
          # public builder.
          self.m.manifest_doctor([
              'public-buildspec', '--paths', gs_path, '--push'
          ], step_name='create external buildspec gs://chromiumos-manifest-versions/{}'
                                 .format(gs_path))

      self._buildspec = ManifestLocation(
          manifest_repo_url=self.MANIFEST_VERSIONS_URL, branch=branch,
          manifest_file=manifest_file, manifest_gs_path=manifest_gs_path)
      self.m.easy.set_properties_step(buildspec_gs_uri=manifest_gs_path)

  def run_payload_generation(self, override_qs_account: str = None):
    """Run the generation of release payloads using the context of a build.

    This is blocking: it will launch the paygen orchestrator, and wait for it to
    finish. This function assumes that it is run after a new release image has
    been built.

    Args:
      override_qs_account: QS Account to use instead of whatever is configured.
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
          'minios': not self._minios_unsupported,
      }
      if override_qs_account:
        paygen_properties['override_qs_account'] = override_qs_account
      request = self.m.buildbucket.schedule_request(
          builder=pg_orch_builder,
          bucket=bucket,
          properties=paygen_properties,
          can_outlive_parent=False,
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(self.m.buildbucket.build.id)),
      )

      builds = None
      timeout = self.m.paygen_orchestration.paygen_orchestrator_timeout_sec
      if self.m.conductor.enabled and self.m.conductor.collect_config(
          'paygen-orch'):
        with self.m.step.nest('running paygen orchestrator'):
          bbids = [b.id for b in self.m.buildbucket.schedule([request])]
          bbids = self.m.conductor.collect('paygen-orch', bbids,
                                           timeout=timeout)
          builds = list(
              self.m.buildbucket.get_multi(
                  bbids, step_name='get', url_title_fn=lambda b: None).values())
      else:
        builds = self.m.buildbucket.run([request], timeout=timeout,
                                        step_name='running paygen orchestrator')

      paygen_orch_build = builds[0]
      if paygen_orch_build.status != common_pb2.SUCCESS:
        build_url = 'https://cr-buildbucket.appspot.com/build/{}'.format(
            paygen_orch_build.id)
        failure = None
        with self.m.step.nest('inspect failure') as presentation:
          presentation.step_text = paygen_orch_build.summary_markdown
          presentation.links[build_url] = build_url
          if paygen_orch_build.status == common_pb2.INFRA_FAILURE:
            presentation.status = self.m.step.INFRA_FAILURE
            failure = InfraFailure
          else:
            presentation.status = self.m.step.FAILURE
            failure = StepFailure
        raise failure('paygen orchestrator failed\n{}'.format(build_url))

      if 'payloads' in paygen_orch_build.output.properties:
        payload_information = paygen_orch_build.output.properties['payloads']
        payload_information = [
            json_format.Parse(payload, BuildReport.Payload())
            for payload in payload_information
        ]
        self.m.build_reporting.publish(
            BuildReport(payloads=payload_information))

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

  def get_image_dir(self, config, sysroot, step) -> str:
    """Determine the image directory unsigned artifacts are uploaded in.

    Args:
      config (BuilderConfig): The Builder Config for the build.
      sysroot (Sysroot): sysroot to use.
      step (StepPresentation): the step to log into.

    Returns:
      GS image directory as a gs:// uri.
    """
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
    gs_path = self.m.cros_artifacts.artifacts_gs_path(config.id.name,
                                                      sysroot.build_target,
                                                      config.id.type,
                                                      template=publish_template)

    # If checkpoint has set an artifact link, use that instead.
    gs_image_dir = self.m.checkpoint.artifact_link or gs_image_dir_template.format(
        gs_bucket=gs_bucket, gs_path=gs_path)
    step.links['gs image dir'] = (
        'https://console.cloud.google.com/storage/browser/{gs_path}'.format(
            gs_path=gs_image_dir[len('gs://'):]))
    return gs_image_dir

  def emit_release_buckets(self, build_target, step):
    """Emit the release buckets for the configured channels in step logs.

    Also creates the "BUILT_BY_RUBIK" sentinel file.

    Args:
      build_target (str): build target to include in the path.
      step (StepPresentation): step to log into.
    """
    for channel in self._channels:
      channel_name = self.m.cros_release_util.channel_to_long_string(channel)
      gs_directory = '{bucket}/{channel}/{build_target}/{version}'.format(
          bucket=self._release_bucket, channel=channel_name,
          build_target=build_target,
          version=str(self.m.cros_version.version.platform_version))
      step.links['gs release dir: %s' % Channel.Name(channel)] = (
          'https://console.cloud.google.com/storage/browser/%s' % gs_directory)
      # TODO(b/230518952): remove this when CPFE issue is resolved.
      self._create_sentinel_file('gs://{}/BUILT_BY_RUBIK'.format(gs_directory))

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
      # Get the gs image directory.
      gs_image_dir = self.get_image_dir(config, sysroot, presentation)
      sysroot = Sysroot(build_target=self.m.build_menu.build_target)
      # Validate sign types given.
      self.validate_sign_types(self._sign_types)

      # Emit release bucket for each channel.
      self.emit_release_buckets(sysroot.build_target.name, presentation)

      response = self.m.cros_artifacts.push_image(
          self.m.build_menu.chroot, gs_image_dir, sysroot,
          sign_types=self._sign_types,
          dest_bucket='gs://' + self._release_bucket, channels=self._channels)
      instructions_uris = [
          i.instructions_file_path for i in response.instructions
      ]
      self.m.easy.set_properties_step(
          signing_instructions_uris=instructions_uris)

      return (gs_image_dir, instructions_uris)

  def set_output_properties(self):
    """Set release-related output properties for the build."""
    self.m.easy.set_properties_step(
        'set release output properties', channels=[
            self.m.cros_release_util.channel_strip_prefix(c)
            for c in self._channels
        ])

  def set_release_qs_account(self):
    """Fetches the RC schedule and determines which QS account to use.

    If the schedule cannot be fetched or is malformatted, reasonable defaults
    will be used. See go/dynamic-rc-prio for more context.
    """
    # TODO(b/278885352): Update docstring to point to g3docs.

    with self.m.step.nest('determine release testing priority') as presentation:

      def get_qs_account():

        def fetch_schedule():
          with self.m.step.nest('fetch schedule json') as presentation:
            result = self.m.gsutil.cat(
                RC_SCHEDULE_URI,
                stdout=self.m.raw_io.output(add_output_log=True), ok_ret='any')

            if result.retcode != 0:
              presentation.step_text = 'could not fetch schedule.json, falling back to defaults'
              presentation.status = self.m.step.FAILURE
              return None

            try:
              schedule_data = json.loads(result.stdout)
            except json.decoder.JSONDecodeError:
              presentation.step_text = 'could not parse schedule.json, falling back to defaults'
              presentation.status = self.m.step.FAILURE
              return None

            # Want a string of the format "YYYY-MM-DD". Regularly scheduled builds
            # span two calendar days, scheduling tests in the early morning. This
            # is the day we want to match up with schedule.json.
            # For LTS this doesn't matter as LTS always gets `release_high_prio`.
            today = self.m.time.utcnow().date().isoformat()
            if today not in schedule_data:
              presentation.step_text = 'could not find {} in schedule.json, falling back to defaults'.format(
                  today)
              presentation.status = self.m.step.FAILURE
              return None

            return schedule_data[today]

        schedule_data = fetch_schedule()

        config = self.m.cros_infra_config.config
        # TODO(b/278885352): Remove special casing for 108 once channels are
        # actually populated with LTS/LTC (this work is targeting 114).
        if config.orchestrator.gitiles_commit.ref == "refs/heads/release-R108-15183.B":
          return RELEASE_HIGH_PRIO_QS_ACCOUNT

        if Channel.CHANNEL_LTS in self._channels or Channel.CHANNEL_LTC in self._channels:
          # LTS is scheduled ad hoc as needed and thus always gets high priority.
          return RELEASE_HIGH_PRIO_QS_ACCOUNT

        if not schedule_data:
          # Apply defaults.
          if Channel.CHANNEL_STABLE in self._channels:
            return RELEASE_HIGH_PRIO_QS_ACCOUNT
          if Channel.CHANNEL_BETA in self._channels:
            return RELEASE_MED_PRIO_QS_ACCOUNT
          return RELEASE_LOW_PRIO_QS_ACCOUNT

        # Stabilize branches should get low priority.
        if not self.m.cros_source.is_tot and 'release' not in config.orchestrator.gitiles_commit.ref:
          return RELEASE_LOW_PRIO_QS_ACCOUNT

        milestone = str(self.m.cros_version.version.milestone)
        if schedule_data['primary'] == milestone:
          return RELEASE_HIGH_PRIO_QS_ACCOUNT
        if schedule_data['secondary'] == milestone:
          return RELEASE_MED_PRIO_QS_ACCOUNT
        return RELEASE_LOW_PRIO_QS_ACCOUNT

      qs_account = get_qs_account()
      self.m.easy.set_properties_step(dynamic_qs_account=qs_account)
      step_text = 'using qs_account "{}"'.format(qs_account)

      if not self._dynamic_qs_account:
        step_text = '(dryrun) ' + step_text
      else:
        self.m.skylab.set_qs_account(qs_account)

      presentation.step_text = step_text

      return qs_account
