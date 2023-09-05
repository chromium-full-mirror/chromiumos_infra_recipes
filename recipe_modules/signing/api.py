# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json
import re
from json import JSONDecodeError
from typing import Any, Dict, List, NewType, Optional

from google.protobuf.text_format import Parse

from PB.chromiumos import common as common_pb2  # pylint: disable=unused-import
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.signing import BuildTargetSigningConfigs
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import recipe_api
from recipe_engine.engine_types import StepPresentation
from recipe_engine.recipe_api import StepFailure

BuildConfig = BuildReport.BuildConfig

# Signing states that convey signing is complete.
_PASSED = 'passed'
_FAILED = 'failed'
_TERMINAL_STATES = [_PASSED, _FAILED]

_STATUS_OBJECT = 'status'
_SIGNING_STATUS = 'status'
_DETAILS = 'details'

INSTRUCTIONS_PATTERN = re.compile(r'^gs://[^/]+/(.*)/[^/]+\.instructions$')

InstructionsMetadata = NewType('InstructionsMetadata', Any)

CONFIG_INTERNAL_REPO_URL = 'https://chrome-internal.googlesource.com/chromeos/config-internal'
SIGNING_CONFIG_FILEPATH = 'board_config/generated/signing_config.textproto'
SIGNING_CONFIG_TEST_DATA = '''build_target_signing_configs {
  build_target: "eve"
  signing_configs {
    keyset: "eve-foo-bar"
    ensure_no_password: true
    firmware_update: true
  }
}'''


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

  # Methods to support the new local signing flow.

  @property
  def local_signing(self) -> bool:
    return self._local_signing

  def get_config(self) -> BuildTargetSigningConfigs:
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
      self._signing_config = signing_config
      return signing_config

  def _setup_signing(
      self,
      sign_types: List['common_pb2.ImageType']) -> BuildTargetSigningConfigs:
    """Set up the working dir for signing.

    Copies all necessary artifacts (based on signing config) from GS into a new
    temp dir and populates the artifact path field in each individual signing
    config.

    Also drops configs for irrelevant sign types.
    """
    config = self.get_config()

    _ = sign_types
    # TODO(b/296086340): Drop configs for irrelevant sign types.

    # TODO(b/296086340): Replicate copy functionality from pushimage.py
    # https://source.corp.google.com/h/chromium/chromiumos/codesearch/+/main:chromite/scripts/pushimage.py;drc=511a7c12bcf28eda77cbe82cc09cddcfd6b15be9;l=441

    # TODO(b/296086340): Populate signing config `artifact_path` field with
    # the path of the relevant archive.

    return config

  def sign_artifacts(
      self, sign_types: Optional[List['common_pb2.ImageType']] = None) -> None:
    """Stub implementation for local signing flow."""
    if not self.local_signing:
      raise StepFailure(
          'Cannot sign artifacts when local signing is not configured')
    _ = self._setup_signing(sign_types)

    # TODO(b/296086340): Handle empty sign_types (release should pass this field
    # in based on cros_release.sign_types, not sure about firmware).

    # TODO(b/296086340): Call BAPI.

    # TODO(b/296086340): rsync working_dir to the appropriate GS dir (for now,
    # be sure to use the throwaway bucket -- eventually we'll want to do
    # chromeos-releases).

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
          if self.get_status_from_instructions(
              instructions_info) in _TERMINAL_STATES:
            # Strip out the directory from the instructions file.
            match = INSTRUCTIONS_PATTERN.match(instructions)
            # Be defensive, make None failures obvious.
            if match:
              instructions_info['release_directory'] = match.group(1)

            instructions_metadata[instructions] = instructions_info

        # Determine if we need to keep polling.
        keep_polling = self._any_empty(instructions_metadata)
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
      if not self.signing_succeeded(metadata):
        if self.signing_failed(metadata):
          failure = self.get_failure(metadata)
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

  @staticmethod
  def signing_succeeded(metadata: Dict[str, InstructionsMetadata]) -> bool:
    """Whether the provided metadata contains a successful signing operation.

    Args:
      metadata: Metadata from the instructions file.

    Returns:
      True/False whether the signing succeeded.
    """
    return SigningApi.get_status_from_instructions(metadata) == _PASSED

  @staticmethod
  def signing_failed(metadata: Dict[str, InstructionsMetadata]) -> bool:
    """Whether the provided metadata contains a failed signing operation.

    Args:
      metadata: Metadata from the instructions file.

    Returns:
      True/False whether the signing failed.
    """
    return SigningApi.get_status_from_instructions(metadata) == _FAILED

  @staticmethod
  def get_status_from_instructions(metadata: Dict[str, InstructionsMetadata]
                                  ) -> Optional[str]:
    """Given an instructions file, pull out the status of the signing operation.

    Args:
      metadata: An instructions metadata file.

    Returns:
      The status of the signing, or None if not available.
    """
    if metadata is None or not _STATUS_OBJECT in metadata or not _SIGNING_STATUS in metadata[
        _STATUS_OBJECT]:
      return None
    return metadata[_STATUS_OBJECT][_SIGNING_STATUS]

  @staticmethod
  def get_failure(metadata: Dict[str, InstructionsMetadata]) -> Optional[str]:
    """Given an instructions file, pull out the failure of signing.

    Args:
      metadata: An instructions metadata file.

    Returns:
      The failure of the signing, or None if not available.
    """
    if metadata is None or not _STATUS_OBJECT in metadata or not _DETAILS in metadata[
        _STATUS_OBJECT]:
      return None
    return metadata[_STATUS_OBJECT][_DETAILS]

  @staticmethod
  def _any_empty(instructions_meta: Dict[str, InstructionsMetadata]) -> bool:
    """Checks to see if any values in the provided dict are None.

    Args:
      instructions_meta: Dict of instructions url -> metadata.

    Returns:
      True if any are None, otherwise false.
    """
    for value in instructions_meta.values():
      if value is None:
        return True

    return False
