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
from typing import Any, Dict, List, NewType, Optional, Tuple, Set

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


# How long to wait on gsutil ops.
GSUTIL_TIMEOUT_SECONDS = 30 * 60
GSUTIL_MAX_RETRY_COUNT = 2

STAGING_KEYSET = 'DevPreMPKeys'
STAGING_KEYSET_TYPE_OVERRIDE = {
    common_pb2.IMAGE_TYPE_ACCESSORY_RWSIG: 'devkeys-acc',
    common_pb2.IMAGE_TYPE_ACCESSORY_USBPD: 'devkeys-acc',
}
IMAGE_TYPE_TO_SUFFIX = {
    common_pb2.IMAGE_TYPE_ACCESSORY_RWSIG: '.tar.bz2',
    common_pb2.IMAGE_TYPE_BASE: '.tar.xz',
    common_pb2.IMAGE_TYPE_FACTORY: '.zip',
    common_pb2.IMAGE_TYPE_FIRMWARE: '.tar.bz2',
    common_pb2.IMAGE_TYPE_RECOVERY: '.tar.xz',
    common_pb2.IMAGE_TYPE_TEST: '.tar.xz',
}

# Artifact types which exist locally and do not need to be downloaded from GS.
LOCAL_ARTIFACT_TYPES = [
    common_pb2.IMAGE_TYPE_SHELLBALL,
]

PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED

# Provenance files are named according to the artifact they're for, with the
# intoto suffix.
BCID_ATTESTATION_NAME = '{artifact_name}.intoto.jsonl'

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
    self._use_dev_keys = properties.use_dev_keys

    self._bcid_policy = properties.bcid_enforcement.bcid_policy or 'chromeosimage://'
    self._signed_prov_generation_fatal = properties.bcid_enforcement.signed_provenance_generation_fatal or False
    self._unsigned_provenance_verification_fatal = properties.bcid_enforcement.unsigned_provenance_verification_fatal or False

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

  @property
  def get_use_dev_keys(self) -> bool:
    return self._use_dev_keys

  @property
  def signed_provenance_generation_fatal(self) -> bool:
    return self._signed_prov_generation_fatal

  @property
  def unsigned_provenance_verification_fatal(self) -> bool:
    return self._unsigned_provenance_verification_fatal

  @property
  def get_bcid_policy(self) -> str:
    return self._bcid_policy

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
    with self.m.step.nest('fetch signing config') as pres:
      try:
        branch = self.m.cros_infra_config.config.orchestrator.gitiles_commit.ref
      except AttributeError as e:
        raise StepFailure('could not get branch from builder config') from e
      signing_config_textproto = self.m.gitiles.download_file(
          CONFIG_INTERNAL_REPO_URL, SIGNING_CONFIG_FILEPATH, branch=branch,
          step_test_data=self.m.signing.test_api.get_config_data)
      signing_config = Parse(signing_config_textproto,
                             BuildTargetSigningConfigs())

      build_target = self.m.build_menu.build_target.name
      for config in signing_config.build_target_signing_configs:
        if config.build_target == build_target:
          # If we're staging or if we specify by property, override the keyset
          # to be the staging keyset.
          if self.m.cros_infra_config.is_staging or self.get_use_dev_keys:
            config.keyset = STAGING_KEYSET
            for signing_config in config.signing_configs:
              if signing_config.image_type in STAGING_KEYSET_TYPE_OVERRIDE:
                signing_config.keyset = STAGING_KEYSET_TYPE_OVERRIDE[
                    signing_config.image_type]
              elif signing_config.keyset:
                signing_config.keyset = STAGING_KEYSET
            pres.logs['override keyset'] = (
                f'Now using: {STAGING_KEYSET} because this is staging or '
                'use_dev_keys property was specified.')
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
                             artifact_names: Set[str]) -> List[str]:
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
        # If the artifact is not found, we don't want to fail the step.
        self.m.step.active_result.presentation.status = self.m.step.SUCCESS
        skipped_artifacts.append(artifact_name)

      try:
        # Also download the attestations for the files, if they exist.
        attestation_name = BCID_ATTESTATION_NAME.format(
            artifact_name=artifact_name)
        self.m.gsutil.download(
            gs_dir, attestation_name,
            self.m.path.join(local_dir, attestation_name),
            name='download {} from {}'.format(attestation_name, gs_dir),
            timeout=GSUTIL_TIMEOUT_SECONDS)
      except StepFailure:
        # If the attestation is not found, we don't want to fail the step.
        # We do not expect attestation files to exist for every artifact, but
        # they must exist for artifacts we're about to try and sign. These
        # attestations will be verified before signing.
        self.m.step.active_result.presentation.status = self.m.step.SUCCESS

    return skipped_artifacts

  def get_common_downloads(
      self, sign_types: List['common_pb2.ImageType']) -> List[str]:
    """Get a list of common files to be downloaded, depending on sign types."""
    # Files to always download for shellballs.
    if any(x in sign_types for x in [
        common_pb2.IMAGE_TYPE_SHELLBALL, common_pb2.IMAGE_TYPE_RECOVERY_KERNEL
    ]):
      return []
    # Files to always download for other sign types.
    build_target = self.m.build_menu.build_target.name
    version = self.m.cros_version.version.platform_version
    return [
        'image.zip',
        'chromiumos_test_image.tar.xz',
        'debug.tgz',
        f'chromeos-hwqual-{build_target}-{version}.tar.bz2',
        'stateful.tgz',
        'dlc',
        'full_dev_part_KERN.bin.gz',
        'full_dev_part_ROOT.bin.gz',
        'full_dev_part_MINIOS.bin.gz',
        'recovery_image.tar.xz',
        'factory_image.zip',
        'firmware_from_source.tar.bz2',
    ]

  def download_release_artifacts(
      self, relevant_signing_configs: List[SigningConfig]
  ) -> Tuple[List[SigningConfig], Path]:
    """Download any needed artifacts so we can support retries with conductor.

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
      sign_types = [sc.image_type for sc in relevant_signing_configs]
      to_download = set(self.get_common_downloads(sign_types))
      signing_configured_artifacts = []

      for signing_config in relevant_signing_configs:
        artifact_name = self.artifact_name_by_image_type(
            signing_config.image_type)
        if artifact_name:
          signing_config.archive_path = artifact_name
          if signing_config.image_type not in LOCAL_ARTIFACT_TYPES:
            to_download.add(artifact_name)
          signing_configured_artifacts.append(artifact_name)

      skipped_artifacts = self.gs_download_if_present(gs_dir, local_dir,
                                                      to_download)
      if skipped_artifacts:
        pres.logs['skipped'] = 'Skipped artifacts not found in GS: {}'.format(
            ','.join(skipped_artifacts))

      if to_download:
        pres.logs[
            'configured'] = 'Downloading artifacts based on signing config: {}'.format(
                ','.join(sorted(to_download)))

      # Local temp dir with artifacts should be group-readable.
      chmod_cmd = ['sudo', '-n', 'chmod', '-R', 'u=rwx,g=r,-t', local_dir]
      self.m.step('changing permissions of %s' % local_dir, chmod_cmd,
                  infra_step=True)

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

  def verify_bcid_attestations_for_unsigned_artifacts(
      self, build_target_config, signing_dir: Path,
      attestation_eligible: bool) -> set:
    """
    Looks in the signing_dir for artifacts we're about to sign, and attempts to
    find their matching attestation files, which should have been downloaded
    earlier. If no attestation exists, or the call to BCID verifier fails, and
    BCID verification is fatal, these steps will fail the build. Otherwise,
    everything will continue as normal.

    Args:
      signing_configs:
        The configs we're going to use when signing. The artifacts configured as
        inputs to signing are the ones we care about verifying provenance for.
      signing_dir: Path to the local directory to check for files.

    Returns: A list of artifacts that failed verification.
    """
    failed_verifications = set()
    if not attestation_eligible:
      return failed_verifications

    with self.m.step.nest('verify provenance for unsigned artifacts'):

      # Use the signing configs to extract the archive path for the artifacts we're
      # going to use as input to signing steps. These are the files we expect to
      # see in the signing_dir with verifiable BCID attestations.
      for signing_config in build_target_config.signing_configs:
        channel = common_pb2.Channel.Name(signing_config.channel)
        artifact_name = signing_config.archive_path

        with self.m.step.nest(
            f'verifying provenance for {channel} {artifact_name}'
        ) as verify_step:
          artifact_path = self.m.path.join(signing_dir, artifact_name)
          attestation_name = BCID_ATTESTATION_NAME.format(
              artifact_name=artifact_name)
          attestation_path = self.m.path.join(signing_dir, attestation_name)

          if not self.m.path.exists(attestation_path):
            failed_verifications.add(artifact_name)

            verify_step.step_summary_text = 'unable to verify. attestation file did not exist in {} for {}'.format(
                signing_dir, artifact_name)
            if self.unsigned_provenance_verification_fatal:
              verify_step.status = self.m.step.FAILURE

            # No attestation, cannot continue with verification
            continue

          try:
            self.m.bcid_verifier.verify_provenance(self.get_bcid_policy,
                                                   artifact_path,
                                                   attestation_path)
          except StepFailure as step_failure:
            failed_verifications.add(artifact_name)

            # For now, only raise exceptions for provenance verification if build properties
            # have provenance verification for unsigned artifacts set to be fatal.
            verify_step.status = self.m.step.FAILURE
            verify_step.step_summary_text = 'attestation verification failed'

            if self.unsigned_provenance_verification_fatal:
              raise step_failure

    return failed_verifications

  def sign_artifacts(
      self,
      sign_types: List['common_pb2.ImageType'],
      channels: List['common_pb2.Channel'],
      include_paygen: bool = True,
      local_artifact_dir: Optional[Path] = None,
      upload_unsigned: Optional[bool] = True,
      attestation_eligible: bool = False,
  ) -> SignImageResponse:
    """Implementation for local signing flow."""
    if not self.local_signing:
      raise StepFailure(
          'Cannot sign artifacts when local signing is not configured')

    with self.m.step.nest('sign artifacts'):
      build_target_config, archive_dir = self.setup_signing(
          sign_types, channels)
      config = BuildTargetSigningConfigs(
          build_target_signing_configs=[build_target_config])

      # Stage local artifacts for signing, if specified.
      if local_artifact_dir:
        with self.m.step.nest('copying local artifacts to prepare for signing'):
          artifacts = self.m.file.listdir('list artifacts to stage for signing',
                                          local_artifact_dir, recursive=True,
                                          test_data=['chromeos-firmwareupdate'])
          for artifact in artifacts:
            self.m.file.copy('stage artifact for signing', artifact,
                             archive_dir)

      self.m.time.exponential_retry(retries=2,
                                    delay=datetime.timedelta(seconds=1))

      def docker_prune():
        """Prunes the docker cache to remove stopped containers. The docker
        root is the boot partition, so we don't want the cache to grow over
        time.
        """
        self.m.step('docker prune', [
            'docker',
            'container',
            'prune',
            '--force',
        ])

      def docker_pull():
        docker_prune()

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

      failed_unsigned_verifications = self.verify_bcid_attestations_for_unsigned_artifacts(
          build_target_config, archive_dir, attestation_eligible)

      gs_dirs = set()
      if include_paygen:
        gs_dirs.update(
            self.stage_paygen_artifacts(build_target_config, channels))
      if upload_unsigned:
        gs_dirs.update(
            self.upload_unsigned_artifacts(archive_dir, build_target_config,
                                           channels))
      for gs_dir in sorted(gs_dirs):
        self.m.bot_cost.set_upload_size(gs_dir)

      docker_tmp_dir = self.m.path.mkdtemp(prefix='signing_tmp_')

      with self.m.step.nest('call BAPI') as presentation:
        request = SignImageRequest(
            signing_configs=config, archive_dir=str(archive_dir),
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=self.m.path.abspath(archive_dir),
                    location=common_pb2.Path.Location.OUTSIDE,
                )), tmp_path=self.m.path.abspath(docker_tmp_dir),
            docker_image=self.signing_docker_image)
        response = self.m.cros_build_api.ImageService.SignImage(request)
        self.add_kms_logs_as_step_logs(presentation, archive_dir)
        # Turn the step red if any failures are present.
        for archive in response.signed_artifacts.archive_artifacts:
          if archive.signing_status != PASSED:
            presentation.status = self.m.step.FAILURE

      self.upload_signed_artifacts(response, attestation_eligible,
                                   failed_unsigned_verifications)

      docker_prune()

      return response

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
    bucket = self.gs_upload_bucket
    gs_dir = self.m.signing_utils.get_gs_dir_for_channel(channel)
    return f'gs://{bucket}/{gs_dir}/'

  def _get_gs_artifact_name(self, build_target: str, version: str,
                            image_type: common_pb2.ImageType) -> str:
    """Map artifacts to versioned name expected for paygen signing.
    """
    img_type = None
    if image_type is not None:
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

          # Files that are always copied if they're present.
          # Logic lifted from pushimage.py.
          files_to_copy = (
              # (<src>, <dst>, <suffix>),
              ('image.zip',
               self._get_gs_artifact_name(build_target_config.build_target,
                                          version, None), 'zip'),
              ('chromiumos_test_image.tar.xz',
               self._get_gs_artifact_name(build_target_config.build_target,
                                          version,
                                          common_pb2.IMAGE_TYPE_TEST), None),
              ('debug.tgz',
               f'debug-{build_target_config.build_target.replace("_", "-")}',
               'tgz'),
              ('chromeos-hwqual-%s-%s.tar.bz2' %
               (build_target_config.build_target, version), None, None),
              ('stateful.tgz', None, None),
              ('dlc', None, None),
              ('full_dev_part_KERN.bin.gz', None, None),
              ('full_dev_part_ROOT.bin.gz', None, None),
              ('full_dev_part_MINIOS.bin.gz', None, None),
              ('recovery_image.tar.xz',
               self._get_gs_artifact_name(build_target_config.build_target,
                                          version,
                                          common_pb2.IMAGE_TYPE_RECOVERY),
               None),
              ('factory_image.zip',
               self._get_gs_artifact_name(build_target_config.build_target,
                                          version,
                                          common_pb2.IMAGE_TYPE_FACTORY), None),
              ('firmware_from_source.tar.bz2',
               self._get_gs_artifact_name(build_target_config.build_target,
                                          version,
                                          common_pb2.IMAGE_TYPE_FIRMWARE),
               None),
          )
          for src, dst, suffix in files_to_copy:
            if dst is None:
              dst = src
            elif suffix is not None:
              dst = f'{dst}.{suffix}'
            src_path = os.path.join(str(archive_dir), src)
            if self.m.path.isfile(src_path):
              uploaded.add(src)
              # -n so we don't clobber existing destination artifacts.
              self.m.gsutil([
                  'cp',
                  '-n',
                  src_path,
                  os.path.join(gs_dir, dst),
              ], multithreaded=True, timeout=GSUTIL_TIMEOUT_SECONDS)

          # Files to sign are copied.
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

  def upload_signed_artifacts(
      self, response: SignImageResponse, attestation_eligible: bool,
      failed_unsigned_artifact_verification: Optional[set] = None) -> None:
    """Uploads all files in output_dir to GS using gsutil cp."""
    if not failed_unsigned_artifact_verification:
      failed_unsigned_artifact_verification = set()

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
          ex = StepFailure(
              'Failed to sign artifact. Check stdout of signing'
              ' build API call for more information. See go/cros-signing-help.')

      if not to_upload_by_channel and not ex:
        presentation.step_text = 'no signed artifacts'
        return

      @exponential_retry(retries=GSUTIL_MAX_RETRY_COUNT,
                         delay=datetime.timedelta(seconds=1))
      def _gs_upload(self, local_path: str, gs_dir: str):
        # -n so we don't clobber existing destination artifacts.
        self.m.gsutil(['cp', '-n', local_path, gs_dir], multithreaded=True,
                      timeout=GSUTIL_TIMEOUT_SECONDS)

      # Keep track of instances where we failed to generate artifact
      # provenance for signed artifacts. This will be set as a build property
      # to enable repoorting.
      failed_prov_generation = set()

      # Upload the artifacts for each channel.
      signed_upload_paths = {}
      for channel, artifacts in to_upload_by_channel.items():
        gs_dir = self._get_gs_path_for_channel(channel)
        signed_upload_paths[self.m.cros_release_util.channel_to_long_string(
            channel)] = gs_dir

        with self.m.step.nest(
            f'upload signed artifacts for {common_pb2.Channel.Name(channel)}'
        ) as pres:
          pres.links['gs upload dir'] = (
              'https://console.cloud.google.com/storage/browser/%s' %
              gs_dir[len('gs://'):])

          for artifact in artifacts:
            local_artifact_path = os.path.join(response.output_archive_dir,
                                               artifact)

            gs_artifact_path = os.path.join(gs_dir, artifact)

            if attestation_eligible:
              # TODO (b/292149463): Enforce provenance generation always.
              with self.m.step.nest('generate signed provenance') as step:
                try:
                  artifact_hash = self.m.file.file_hash(local_artifact_path,
                                                        test_data='deadbeef')
                  self.m.bcid_reporter.report_gcs(artifact_hash,
                                                  gs_artifact_path)
                except StepFailure as step_failure:
                  failed_prov_generation.add(artifact)
                  step.status = self.m.step.FAILURE
                  step.step_summary_text = 'Failed to generate signed provenance.'

                  # For now, only raise exceptions for signed provenance generation if build properties
                  # have signed provenance generation set to be fatal.
                  if self.signed_provenance_generation_fatal:
                    raise step_failure

            _gs_upload(self, local_artifact_path, gs_dir)

      self.m.easy.set_properties_step(
          **{'signed_upload_paths': signed_upload_paths})

      self.m.easy.set_properties_step(
          **{
              'bcid': {
                  'failed_unsigned_prov_verification':
                      list(failed_unsigned_artifact_verification),
                  'failed_signed_prov_generation':
                      list(failed_prov_generation)
              }
          })

      if ex:
        raise ex

  def get_shellball_versions(
      self, channels: List[common_pb2.Channel]) -> Dict[str, str]:
    """Returns mapping of channel -> shellball version.

    Fetch LATEST-SHELLBALL per-channel from GS and increment to return the new
    version. Shellball versions are separate from platform version since they
    are based on pinned config.
    """
    current_shellball_versions = self.m.signing_utils.get_current_shellball_versions(
        channels, self.gs_upload_bucket)
    return self.m.signing_utils.increment_shellball_major_versions(
        current_shellball_versions)

  def upload_shellball_latest_files(self,
                                    shellball_versions: Dict[str, str]) -> None:
    """Upload LATEST-SHELLBALL files per channel."""
    latest_filename = 'LATEST-SHELLBALL'
    for channel_str, shellball_version in shellball_versions.items():
      local_version_file_path = self.m.path.cleanup_dir / f'{channel_str}-{latest_filename}'
      self.m.file.write_text(f'write latest file for {channel_str}',
                             local_version_file_path, shellball_version)

      remote_version_file_bucket = f'{self.gs_upload_bucket}/{channel_str}/{self.m.build_menu.build_target.name}'
      self.m.gsutil.upload(local_version_file_path, remote_version_file_bucket,
                           latest_filename,
                           name='upload {}'.format(latest_filename))
    self.m.easy.set_properties_step(**{latest_filename: shellball_versions})
