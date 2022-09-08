# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import re

from recipe_engine import recipe_api
from PB.chromiumos.build_report import BuildReportBeta as BuildReport

BuildConfig = BuildReport.BuildConfig

# Signing states that convey signing is complete.
_PASSED = 'passed'
_FAILED = 'failed'
_TERMINAL_STATES = [_PASSED, _FAILED]

_STATUS = 'status'

INSTRUCTIONS_PATTERN = re.compile(r'^gs://[^/]+/(.*)/[^/]+\.instructions$')


class CrosSigningApi(recipe_api.RecipeApi):
  """A module to encapsulate communication with the signing fleet."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosSigningApi, self).__init__(*args, **kwargs)
    self._timeout = properties.timeout or 4 * 60 * 60
    self._sleep_duration = properties.sleep_duration or 5 * 60

  def wait_for_signing(self, instructions_list):
    """Wait for signing to complete for a set of instructions files.

    This method polls each instructions file for metadata, and waits for that
    metadata to become present, then checks to see if a terminal passing or
    failed state has been achieved. This method returns when either a) signing
    is complete for all of the provided instructions files, or b) the configured
    timeout has elapsed.

    Args:
      instructions_list (list[str]): List of GS URIs for instructions files.

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
      while self._any_empty(instructions_metadata):
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
            instructions_info = json.loads(metadata.stdout.strip())
          # TODO(b/217973271) - this needs to be updated to JSONDecodeError as
          # part of py3 migration.
          except ValueError:
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

        # Sleep.
        self.m.time.sleep(self._sleep_duration)

    return instructions_metadata

  def get_signed_build_metadata(self, instructions_metadata):
    """Get the metadata of the signed build.

    Note - this requires that wait_for_signing has been called and is complete.

    Args:
      instructions_metadata (dict): The metadata dict returned from
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

  def verify_signing_success(self, instructions_metadata):
    """Verifies that the signing operation succeeded."""
    for metadata in instructions_metadata.values():
      if not self.signing_succeeded(metadata):
        raise recipe_api.StepFailure(
            'One or more signing requests failed or timed out. '
            'See full metadata in step "parse metadata".')

  @staticmethod
  def signing_succeeded(metadata):
    """Whether the provided metadata contains a successful signing operation.

    Args:
      metadata (dict): Metadata from the instructions file.

    Returns:
      True/False whether the signing succeeded.
    """
    return CrosSigningApi.get_status_from_instructions(metadata) == _PASSED

  @staticmethod
  def get_status_from_instructions(instructions):
    """Given an instructions file, pull out the status of the signing operation.

    Args:
      instructions (dict): An instructions metadata file.

    Returns:
      The status of the signing, or None if not available.
    """
    if instructions is None or not _STATUS in instructions:
      return None
    return instructions[_STATUS][_STATUS]

  @staticmethod
  def _any_empty(instructions_meta):
    """Checks to see if any values in the provided dict are None.

    Args:
      instructions_meta (dict): Dict of instructions url -> metadata.

    Returns:
      True if any are None, otherwise false.
    """
    for value in instructions_meta.values():
      if value is None:
        return True

    return False
