# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing helpers for signing functionality."""

import json
from typing import Any, Dict, List, NewType, Optional

from google.protobuf.json_format import MessageToDict

from recipe_engine import recipe_api

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos import signing as signing_pb2

# Proto imports for readability.
Version = BuildReport.SignedBuildMetadata.Version
VERSION_KIND_PLATFORM = \
 BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_PLATFORM
VERSION_KIND_MILESTONE = \
 BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_MILESTONE
VERSION_KIND_KEY_FIRMWARE_KEY = \
 BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_KEY_FIRMWARE_KEY
VERSION_KIND_KEY_FIRMWARE = \
 BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_KEY_FIRMWARE
VERSION_KIND_KEY_KERNEL_KEY = \
 BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_KEY_KERNEL_KEY
VERSION_KIND_KEY_KERNEL = \
  BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_KEY_KERNEL

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

  # TODO(b/315495109): Remove instructions methods with legacy signing.
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

  def get_platform_version(self) -> Version:
    return Version(kind=VERSION_KIND_PLATFORM,
                   value=f'{self.m.cros_version.version.platform_version}')

  def get_milestone_version(self) -> Version:
    return Version(kind=VERSION_KIND_MILESTONE,
                   value=f'{self.m.cros_version.version.milestone}')

  def get_keyset_version_list(
      self, archive: signing_pb2.ArchiveArtifacts) -> List[Version]:
    return [
        Version(kind=VERSION_KIND_KEY_FIRMWARE_KEY,
                value=f'{archive.keyset_versions.firmware_key_version}'),
        Version(kind=VERSION_KIND_KEY_FIRMWARE,
                value=f'{archive.keyset_versions.firmware_version}'),
        Version(kind=VERSION_KIND_KEY_KERNEL_KEY,
                value=f'{archive.keyset_versions.kernel_key_version}'),
        Version(kind=VERSION_KIND_KEY_KERNEL,
                value=f'{archive.keyset_versions.kernel_version}'),
    ]

  def signing_response_to_metadata(
      self, sign_image_response: SignImageResponse
  ) -> List[BuildReport.SignedBuildMetadata]:
    """Translate signing response to metadata of the signed build.

    Used for BuildReport in pubsub.

    Args:
      sign_image_response: Response from SignImage.

    Returns:
      List of signed builds (one per signed build image).
    """
    with self.m.step.nest('parse SignImageResponse') as presentation:
      local_artifact_dir = sign_image_response.output_archive_dir
      signed_builds = []
      for archive in sign_image_response.signed_artifacts.archive_artifacts:
        # Skip archives without a channel.
        if not archive.channel:
          continue
        signed_build = BuildReport.SignedBuildMetadata()
        signed_build.board = archive.build_target
        signed_build.channel = archive.channel
        signed_build.type = archive.image_type
        signed_build.keyset = archive.keyset
        # TODO(b/312237673): Pass through keyset_is_mp from signing.
        signed_build.release_directory = local_artifact_dir
        signed_build.status = archive.signing_status

        all_versions = [
            self.m.signing_utils.get_platform_version(),
            self.m.signing_utils.get_milestone_version()
        ] + self.m.signing_utils.get_keyset_version_list(archive)

        signed_build.versions.extend(all_versions)

        for signed_art in archive.signed_artifacts:
          file_with_hashes = signed_build.files.add()
          file_name = signed_art.signed_artifact_name
          file_abspath = self.m.path.join(local_artifact_dir, file_name)
          file_with_hashes.filename = file_name
          file_with_hashes.size = self.m.file.filesizes('compute file size',
                                                        [file_abspath])[0]
          # TODO(b/310256594): Pass through hashes from signing.
          # file_with_hashes.md5 = ''
          # file_with_hashes.sha1 = ''
          # file_with_hashes.sha256 = ''
        signed_builds.append(signed_build)

        presentation.logs['signed build metadata'] = json.dumps(
            [MessageToDict(signed_build) for signed_build in signed_builds],
            indent=2)

      return signed_builds
