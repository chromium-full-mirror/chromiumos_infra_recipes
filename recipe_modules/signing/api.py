# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing signing functionality."""

import collections
import copy
import datetime
import json
import os
import re
from json import JSONDecodeError
from typing import Any, Dict, List, NewType, Tuple

from google.protobuf.text_format import Parse

from PB.chromite.api.image import SignImageRequest, SignImageResponse
from PB.chromiumos import build_report as build_report_pb2  # pylint: disable=unused-import
from PB.chromiumos import common as common_pb2  # pylint: disable=unused-import
from PB.chromiumos import signing as signing_pb2  # pylint: disable=unused-import
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.signing import BuildTargetSigningConfigs, BuildTargetSigningConfig, SigningConfig
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.engine_types import StepPresentation
from recipe_engine.recipe_api import StepFailure

from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

BuildConfig = BuildReport.BuildConfig

INSTRUCTIONS_PATTERN = re.compile(r'^gs://[^/]+/(.*)/[^/]+\.instructions$')

InstructionsMetadata = NewType('InstructionsMetadata', Any)

CONFIG_INTERNAL_REPO_URL = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
SIGNING_CONFIG_FILEPATH = 'board_config/generated/signing_config.textproto'
SIGNING_CONFIG_TEST_DATA = '''build_target_signing_configs {
  build_target: "kukui"
  keyset: "kukui-foo-bar"
  signing_configs {
    image_type: IMAGE_TYPE_BASE
    keyset: "kukui-foo-bar"
    ensure_no_password: true
    firmware_update: true
  }
  signing_configs {
    image_type: IMAGE_TYPE_FACTORY
    keyset: "kukui-foo-bar-factory"
    ensure_no_password: true
    firmware_update: true
  }
  signing_configs {
    image_type: IMAGE_TYPE_FIRMWARE
    ensure_no_password: true
    firmware_update: true
  }
  signing_configs {
    image_type: IMAGE_TYPE_RECOVERY
    ensure_no_password: true
    firmware_update: true
  }
}'''


# How long to wait on gsutil ops.
GSUTIL_TIMEOUT_SECONDS = 30 * 60
GSUTIL_MAX_RETRY_COUNT = 2

STAGING_KEYSET = 'DevPreMPKeys'
IMAGE_TYPE_TO_SUFFIX = {
    common_pb2.IMAGE_TYPE_ACCESSORY_RWSIG: '.tar.bz2',
    common_pb2.IMAGE_TYPE_BASE: '.tar.xz',
    common_pb2.IMAGE_TYPE_FACTORY: '.zip',
    common_pb2.IMAGE_TYPE_FIRMWARE: '.tar.bz2',
    common_pb2.IMAGE_TYPE_RECOVERY: '.tar.xz',
    common_pb2.IMAGE_TYPE_TEST: '.tar.xz',
}

PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED


class SigningApi(recipe_api.RecipeApi):
  """A module to encapsulate signing operations."""

  def __init__(self, properties: SigningProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # Props for the legacy signing fleet.
    self._timeout: int = properties.timeout or 4 * 60 * 60
    self._sleep_duration: int = properties.sleep_duration or 5 * 60
    self.ignore_already_exists_errors: bool = properties.ignore_already_exists_errors
    # Props for the new local signing flow.
    self._local_signing = properties.local_signing or False
    self._signing_config = None
    self._signing_image = None
    self._gs_upload_bucket = properties.gs_upload_bucket or 'chromeos-throw-away-bucket'
    self._paygen_keyset = None

  def initialize(self) -> None:
    """Initialize method for setup that needs the modules instantiated."""
    if self._test_data.enabled:
      self._signing_image = 'signing:latest:'
    else:  # pragma: no cover
      self._signing_image = self.m.file.read_text(
          'read signing image version',
          self.repo_resource('infra', 'config',
                             'signing-docker-image.version')).strip()
    self._signing_image = f'us-docker.pkg.dev/chromeos-bot/signing/{self._signing_image}'

  # Methods to support the new local signing flow.

  @property
  def local_signing(self) -> BuildTargetSigningConfigs:
    return self._local_signing

  @property
  def signing_docker_image(self) -> str:
    return self._signing_image

  @property
  def gs_upload_bucket(self) -> str:
    return self._gs_upload_bucket

  def get_paygen_keyset(self) -> str:
    """Return the keyset for use in paygen.

    Can only be called after setup_signing.

    Raises:
      ValueError, if there is no keyset configured for paygen.
    """
    if not self._paygen_keyset:
      raise ValueError('no paygen keyset configured')
    return self._paygen_keyset

  # TODO(b/315495109): Remove with legacy signing.
  # Methods to support the legacy signing fleet flow.
  def wait_for_signing(self, instructions_list: List[str]
                      ) -> Dict[str, InstructionsMetadata]:
    """Wait for signing to complete for a set of instructions files.

    This method polls each instructions file for metadata, and waits for that
    metadata to become present, then checks to see if a terminal passing or
    failed state has been achieved. This method returns when either a) signing
    is complete for all of the provided instructions files, or b) the configured
    timeout has elapsed.

    Args:
      instructions_list: List of GS URIs for instructions files.

    Returns
      A dict of instruction file location -> instruction metadata for all
      complete signing operations.
    """
    # Set up return object.
    instructions_metadata = {}
    # Get start time for timeout purposes.
    start_time = self.m.time.utcnow()
    with self.m.step.nest('wait for signing to complete'):
      # Place each instructions location in the dict.
      for instructions in sorted(instructions_list):
        # Fail fast if the instructions file doesn't match the expected pattern.
        if not INSTRUCTIONS_PATTERN.match(instructions):
          raise recipe_api.StepFailure(
              'invalid locations file format: {}'.format(instructions))
        instructions_metadata[instructions] = None

      # Start poller.
      keep_polling = True
      while keep_polling:
        # Check against timeout.
        duration = self.m.time.utcnow() - start_time
        if duration.total_seconds() > self._timeout:
          break

        # Look up each instructions file.
        for (instructions, meta) in instructions_metadata.items():
          if meta is not None:
            continue

          # Retrieve instructions metadata and read the file contents.
          metadata = self.m.gsutil.cat(
              instructions + '.json',
              name='reading instructions for {}'.format(instructions + '.json'),
              stdout=self.m.raw_io.output(),
              ok_ret=(0, 1),
          )
          # If the file hasn't landed yet, continue and sleep.
          if metadata.retcode != 0 or not metadata.stdout:
            continue
          # Try to parse the json contents of the metadata.
          try:
            instructions_info: InstructionsMetadata = json.loads(
                metadata.stdout.strip())
          except JSONDecodeError:
            # If the json is malformed, treat it like a missing file.
            continue

          # Check the status

          sig_status = self.m.signing_utils.get_status_from_instructions(
              instructions_info)
          if self.m.signing_utils.is_terminal_status(sig_status):
            # Strip out the directory from the instructions file.
            match = INSTRUCTIONS_PATTERN.match(instructions)
            # Be defensive, make None failures obvious.
            if match:
              instructions_info['release_directory'] = match.group(1)

            instructions_metadata[instructions] = instructions_info

        # Determine if we need to keep polling.
        keep_polling = self.m.signing_utils.any_empty(instructions_metadata)
        # Sleep as long as we need to poll again.
        if keep_polling:
          self.m.time.sleep(self._sleep_duration)

    return instructions_metadata

  def get_signed_build_metadata(
      self, instructions_metadata: Dict[str, InstructionsMetadata]
  ) -> List[InstructionsMetadata]:
    """Get the metadata of the signed build.

    Note - this requires that wait_for_signing has been called and is complete.

    Args:
      instructions_metadata: The metadata dict returned from
        wait_for_signing.

    Returns:
      List of signed build metadata dicts (one per signed build image).
    """
    if not instructions_metadata:
      raise recipe_api.StepFailure(
          'wait_for_signing must be called before get_signed_build_metadata')
    with self.m.step.nest('parse metadata') as presentation:
      presentation.logs['signed build metadata'] = json.dumps(
          instructions_metadata, indent=2, sort_keys=True,
          separators=(',', ':'))

    return list(instructions_metadata.values())

  # TODO(b/315495109): Remove with legacy signing.
  def verify_signing_success(
      self, instructions_metadata: Dict[str, InstructionsMetadata],
      pres: StepPresentation):
    """Verifies that the signing operation succeeded."""
    failed = False
    signing_summary = {}
    for (instructions, metadata) in instructions_metadata.items():
      # Once we've waited our timeout period, signing can be in one of a variety
      # of states: succeeded, failed, still running (i.e. timed out), still
      # pending (i.e. also timed out), or other partial states (i.e. timed out).
      # We consider "passed" success, "failed" a failure, and anything else
      # "Timed Out".
      status = 'PASSED'
      if not self.m.signing_utils.signing_succeeded(metadata):
        if self.m.signing_utils.signing_failed(metadata):
          failure = self.m.signing_utils.get_failure(metadata)
          pres.logs[instructions] = failure
          status = 'FAILED'
          # If ignore_already_exists_errors is set, don't go red.
          if self.ignore_already_exists_errors and 'ImageAlreadyExistsError' in failure:
            status = 'PREVIOUSLY_PASSED'
          else:
            failed = True
        else:
          pres.logs[instructions] = 'Timed Out.'
          status = 'TIMED_OUT'
          failed = True
      signing_summary[instructions] = status
    self.m.easy.set_properties_step(signing_summary=signing_summary)
    if failed:
      raise recipe_api.StepFailure(
          'One or more signing requests failed or timed out. '
          'See output in step "get signed build metadata" or full metadata in '
          'step "parse metadata".')

  def get_config(self) -> BuildTargetSigningConfig:
    """Fetch signing config from the appropriate branch of config-internal."""
    if self._signing_config:
      return self._signing_config
    with self.m.step.nest('fetch signing config'):
      try:
        branch = self.m.cros_infra_config.config.orchestrator.gitiles_commit.ref
      except AttributeError as e:
        raise StepFailure('could not get branch from builder config') from e
      signing_config_textproto = self.m.gitiles.download_file(
          CONFIG_INTERNAL_REPO_URL, SIGNING_CONFIG_FILEPATH, branch=branch,
          step_test_data=lambda: self.m.gitiles.test_api.make_encoded_file(
              SIGNING_CONFIG_TEST_DATA))
      signing_config = Parse(signing_config_textproto,
                             BuildTargetSigningConfigs())

      build_target = self.m.build_menu.build_target.name
      for config in signing_config.build_target_signing_configs:
        if config.build_target == build_target:
          # If we're staging, override the keyset to be the staging keyset.
          if self.m.cros_infra_config.is_staging:
            config.keyset = STAGING_KEYSET
            for signing_config in config.signing_configs:
              if signing_config.keyset:
                signing_config.keyset = STAGING_KEYSET

          self._signing_config = config
          return self._signing_config
      raise StepFailure(
          f'could not find signing config for build target "{build_target}"')

  def _set_fields_for_config(self, config: SigningConfig,
                             channel: common_pb2.Channel) -> SigningConfig:
    config = copy.deepcopy(config)
    config.channel = channel
    # Always set recovery_zip to be true.
    config.recovery_zip = True
    return config

  # Public method so we can test it.
  def setup_signing(
      self, sign_types: List['common_pb2.ImageType'],
      channels: List['common_pb2.Channel']
  ) -> Tuple[BuildTargetSigningConfig, Path]:
    """Set up the working dir for signing.

    Copies all necessary artifacts (based on signing config) from GS into a new
    temp dir and populates the artifact path field in each individual signing
    config.

    Also drops configs for irrelevant sign types.

    Returns:
      - signing configs
      - dir containing input artifacts
    """
    build_target_config = self.get_config()

    self._paygen_keyset = build_target_config.keyset

    relevant_configs = []
    for signing_config in build_target_config.signing_configs:
      if signing_config.image_type in sign_types:
        relevant_configs.append(signing_config)

    relevant_configs, archive_dir = self.download_release_artifacts(
        relevant_configs)

    # Create a copy of config for each configured channel.
    channel_configs = []
    for channel in channels:
      channel_configs.extend([
          self._set_fields_for_config(config, channel)
          for config in relevant_configs
      ])

    build_target_config = BuildTargetSigningConfig(
        build_target=build_target_config.build_target,
        keyset=build_target_config.keyset,
        version=self.m.cros_version.version.platform_version,
        signing_configs=channel_configs,
    )
    return build_target_config, archive_dir

  def artifact_name_by_image_type(self,
                                  image_type: common_pb2.ImageType) -> str:
    """Mapping of image type to artifact name."""
    return self.m.cros_artifacts.artifacts_by_image_type.get(image_type, None)

  @exponential_retry(retries=GSUTIL_MAX_RETRY_COUNT,
                     delay=datetime.timedelta(seconds=1))
  def gs_download_if_present(self, gs_dir: str, local_dir: str,
                             artifact_names: List[str]) -> List[str]:
    """Download from Google Storage if present.

    Returns a list of skipped artifacts.
    """
    skipped_artifacts = []
    for artifact_name in sorted(artifact_names):
      try:
        self.m.gsutil.download(
            gs_dir, artifact_name, self.m.path.join(local_dir, artifact_name),
            name='download {} from {}'.format(artifact_name, gs_dir),
            timeout=GSUTIL_TIMEOUT_SECONDS)
      except StepFailure:
        skipped_artifacts.append(artifact_name)
    return skipped_artifacts

  def download_release_artifacts(
      self, relevant_signing_configs: List[SigningConfig]
  ) -> Tuple[List[SigningConfig], Path]:
    """Download artifacts so we can support retries with conductor.

    As opposed to in situ builds with local artifacts already present.

    Args:
      build_target: Name of build target.
      relevant_signing_configs: Build target configs with supported sign types.

    Returns:
      - relevant_signing_configs with local artifact paths populated.
      - dir containing input artifacts
    """
    local_dir = self.m.path.mkdtemp('signing-dir')
    gs_dir = self.m.build_menu.artifacts_gs_path()[len('gs://'):]

    # Otherwise, only the image types specified in |sign_types| are marked for
    # signing.
    with self.m.step.nest('download release artifacts') as pres:
      to_download = set()
      signing_configured_artifacts = []

      for signing_config in relevant_signing_configs:
        artifact_name = self.artifact_name_by_image_type(
            signing_config.image_type)
        if artifact_name:
          signing_config.archive_path = artifact_name
          to_download.add(artifact_name)
          signing_configured_artifacts.append(artifact_name)

      skipped_artifacts = self.gs_download_if_present(gs_dir, local_dir,
                                                      to_download)
      if skipped_artifacts:
        pres.logs['skipped'] = 'Skipped artifacts not found in GS: {}'.format(
            ','.join(skipped_artifacts))

      if signing_configured_artifacts:
        pres.logs[
            'configured'] = 'Downloading artifacts based on signing config: {}'.format(
                ','.join(signing_configured_artifacts))

      return relevant_signing_configs, local_dir

  def stage_paygen_artifacts(self,
                             build_target_config: BuildTargetSigningConfig,
                             channels: List['common_pb2.Channel']) -> List[str]:
    """Copy the artifacts needed for paygen into the appropriate GS locations.

    Returns:
      List of GS dirs that were pushed to.
    """
    src_gs_dir = self.m.build_menu.artifacts_gs_path()
    version = self.m.cros_version.version.legacy_version

    def _get_gs_artifact_name_wrapper(image_type: 'common_pb2.ImageType'):
      return lambda build_target, version: self._get_gs_artifact_name(
          build_target, version, image_type)

    files_to_copy = {
        # Required for paygen -- the unsigned test image is used in n2n
        # payloads.
        'chromiumos_test_image.tar.xz':
            _get_gs_artifact_name_wrapper(common_pb2.IMAGE_TYPE_TEST),
    }

    # Otherwise, only the image types specified in |sign_types| are marked for
    # signing.
    with self.m.step.nest('stage paygen artifacts'):
      gs_dirs = []
      for channel in channels:
        with self.m.step.nest(
            f'for channel {common_pb2.Channel.Name(channel)}'):
          dest_gs_dir = self._get_gs_path_for_channel(channel)
          gs_dirs.append(dest_gs_dir)
          for src_file, upload_path in files_to_copy.items():

            artifact_upload_name = upload_path(build_target_config.build_target,
                                               version)
            # -n so we don't clobber existing destination artifacts.
            self.m.gsutil([
                'cp',
                '-n',
                os.path.join(src_gs_dir, src_file),
                os.path.join(dest_gs_dir, artifact_upload_name),
            ], multithreaded=True, timeout=GSUTIL_TIMEOUT_SECONDS)
      return gs_dirs


  def sign_artifacts(
      self, sign_types: List['common_pb2.ImageType'],
      channels: List['common_pb2.Channel']
  ) -> List[BuildReport.SignedBuildMetadata]:
    """Implementation for local signing flow."""
    if not self.local_signing:
      raise StepFailure(
          'Cannot sign artifacts when local signing is not configured')

    with self.m.step.nest('sign artifacts'):
      build_target_config, archive_dir = self.setup_signing(
          sign_types, channels)
      config = BuildTargetSigningConfigs(
          build_target_signing_configs=[build_target_config])

      self.m.time.exponential_retry(retries=2,
                                    delay=datetime.timedelta(seconds=1))

      def docker_pull():
        # BAPI is hermetic so need to pull down the specified docker image
        # ahead of time.
        self.m.step('docker pull', [
            'docker',
            'pull',
            self.signing_docker_image,
        ])

      # Make sure we're authenticated.
      self.m.step('docker auth', [
          'gcloud',
          'auth',
          'configure-docker',
          'us-docker.pkg.dev',
      ])
      docker_pull()

      gs_dirs = set()
      gs_dirs.update(self.stage_paygen_artifacts(build_target_config, channels))
      gs_dirs.update(
          self.upload_unsigned_artifacts(archive_dir, build_target_config,
                                         channels))
      for gs_dir in sorted(gs_dirs):
        self.m.bot_cost.set_upload_size(gs_dir)

      with self.m.step.nest('call BAPI') as presentation:
        request = SignImageRequest(
            signing_configs=config, archive_dir=str(archive_dir),
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=self.m.path.abspath(archive_dir),
                    location=common_pb2.Path.Location.OUTSIDE,
                )), docker_image=self.signing_docker_image)
        response = self.m.cros_build_api.ImageService.SignImage(request)
        self.add_kms_logs_as_step_logs(presentation, archive_dir)

      self.upload_signed_artifacts(response)

      return self.m.signing_utils.signing_response_to_metadata(response)

  def add_kms_logs_as_step_logs(self, presentation: StepPresentation,
                                result_path: Path):
    """Add the CloudKMS logs to the given step presentation.

    Args:
      presentation: The step presentation to add logs to.
      result_path: The result_path passed to the signing call.
    """
    with self.m.step.nest('read cloudkms logs'):
      kms_log_dir = result_path / 'cloudkms-logs'
      kms_log_files = self.m.file.listdir(f'list {kms_log_dir}', kms_log_dir)
      for log_file in kms_log_files:
        filename = self.m.path.basename(log_file)
        log_contents = self.m.file.read_text(f'read {filename}', log_file)
        presentation.logs[filename] = log_contents

  def _get_gs_path_for_channel(self, channel: common_pb2.Channel) -> str:
    """Get the gs path for the given channel.

    Example:
      gs://{bucket}/dev-channel/atlas-signingnext/123.0.0/
    """
    channel = self.m.cros_release_util.channel_to_long_string(channel)
    bucket = self.gs_upload_bucket
    build_target = self.m.build_menu.build_target.name
    version = self.m.cros_version.version.platform_version
    return f'gs://{bucket}/{channel}/{build_target}/{version}/'

  def _get_gs_artifact_name(self, build_target: str, version: str,
                            image_type: common_pb2.ImageType) -> str:
    """Map artifacts to versioned name expected for paygen signing.
    """
    img_type = self.m.cros_release_util.image_type_to_str(image_type)
    img = ('%s-' % img_type) if img_type else ''
    suffix = IMAGE_TYPE_TO_SUFFIX.get(image_type, '')
    return 'ChromeOS-%s%s-%s%s' % (img, version, build_target, suffix)

  @exponential_retry(retries=GSUTIL_MAX_RETRY_COUNT,
                     delay=datetime.timedelta(seconds=1))
  def upload_unsigned_artifacts(
      self, archive_dir: Path, build_target_config: BuildTargetSigningConfig,
      channels: List['common_pb2.Channel']) -> List[str]:
    """Uploads files from archive_dir to GS based on signing config.

    Returns:
      List of GS dirs that were pushed to.
    """
    with self.m.step.nest(
        f'upload unsigned artifacts to {self.gs_upload_bucket} bucket'):
      gs_dirs = []
      for channel in channels:
        gs_dir = self._get_gs_path_for_channel(channel)
        gs_dirs.append(gs_dir)

        with self.m.step.nest(
            f'upload unsigned artifacts for {common_pb2.Channel.Name(channel)}'
        ) as presentation:
          presentation.links['gs upload dir'] = (
              'https://console.cloud.google.com/storage/browser/%s' %
              gs_dir[len('gs://'):])

          uploaded = set()

          version = self.m.cros_version.version.legacy_version
          for signing_config in build_target_config.signing_configs:
            artifact_upload_name = self._get_gs_artifact_name(
                build_target_config.build_target, version,
                signing_config.image_type)
            uploaded.add(signing_config.archive_path)
            # -n so we don't clobber existing destination artifacts.
            self.m.gsutil([
                'cp',
                '-n',
                os.path.join(str(archive_dir), signing_config.archive_path),
                os.path.join(gs_dir, artifact_upload_name),
            ], multithreaded=True, timeout=GSUTIL_TIMEOUT_SECONDS)
      return gs_dirs

  def upload_signed_artifacts(self, response: SignImageResponse) -> None:
    """Uploads all files in output_dir to GS using gsutil cp."""
    with self.m.step.nest(
        f'upload signed artifacts to {self.gs_upload_bucket} bucket'
    ) as presentation:
      to_upload_by_channel = collections.defaultdict(lambda: [])
      ex = None

      # Group artifacts by channel so that we can organize steps better.
      for archive_artifacts in response.signed_artifacts.archive_artifacts:
        channel = archive_artifacts.channel
        if not channel:
          presentation.step_text = 'skipping artifacts with no channel'
          continue
        if archive_artifacts.signing_status == PASSED:
          for signed_artifact in archive_artifacts.signed_artifacts:
            to_upload_by_channel[channel].append(
                signed_artifact.signed_artifact_name)
        else:
          # Allow for any success artifacts to upload, so just store the
          # exception.
          ex = StepFailure('Failed to sign artifact. Check stdout of signing'
                           ' build API call for more information.')

      if not to_upload_by_channel and not ex:
        presentation.step_text = 'no signed artifacts'
        return

      @exponential_retry(retries=GSUTIL_MAX_RETRY_COUNT,
                         delay=datetime.timedelta(seconds=1))
      def _gs_upload(self, local_path: str, gs_dir: str):
        # -n so we don't clobber existing destination artifacts.
        self.m.gsutil(['cp', '-n', local_path, gs_dir], multithreaded=True,
                      timeout=GSUTIL_TIMEOUT_SECONDS)

      # Upload the artifacts for each channel.
      for channel, artifacts in to_upload_by_channel.items():
        gs_dir = self._get_gs_path_for_channel(channel)

        with self.m.step.nest(
            f'upload signed artifacts for {common_pb2.Channel.Name(channel)}'
        ) as pres:
          pres.links['gs upload dir'] = (
              'https://console.cloud.google.com/storage/browser/%s' %
              gs_dir[len('gs://'):])

          for artifact in artifacts:
            _gs_upload(self, os.path.join(response.output_archive_dir,
                                          artifact), gs_dir)

      if ex:
        raise ex
