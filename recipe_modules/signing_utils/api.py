# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing helpers for signing functionality."""

from typing import Any, Dict, NewType, Optional

from recipe_engine import recipe_api

# Signing states that convey signing is complete.
_PASSED = 'passed'
_FAILED = 'failed'
_TERMINAL_STATES = [_PASSED, _FAILED]

_STATUS_OBJECT = 'status'
_SIGNING_STATUS = 'status'
_DETAILS = 'details'

InstructionsMetadata = NewType('InstructionsMetadata', Any)


class SigningUtilsApi(recipe_api.RecipeApi):
  """A module to encapsulate helpers for signing operations."""

  @staticmethod
  def signing_succeeded(metadata: Dict[str, InstructionsMetadata]) -> bool:
    """Whether the provided metadata contains a successful signing operation.

    Args:
      metadata: Metadata from the instructions file.

    Returns:
      True/False whether the signing succeeded.
    """
    return SigningUtilsApi.get_status_from_instructions(metadata) == _PASSED

  @staticmethod
  def signing_failed(metadata: Dict[str, InstructionsMetadata]) -> bool:
    """Whether the provided metadata contains a failed signing operation.

    Args:
      metadata: Metadata from the instructions file.

    Returns:
      True/False whether the signing failed.
    """
    return SigningUtilsApi.get_status_from_instructions(metadata) == _FAILED

  @staticmethod
  def is_terminal_status(status: str) -> bool:
    return status in _TERMINAL_STATES

  @staticmethod
  def get_status_from_instructions(
      metadata: Dict[str, InstructionsMetadata]) -> Optional[str]:
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
  def any_empty(instructions_meta: Dict[str, InstructionsMetadata]) -> bool:
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
