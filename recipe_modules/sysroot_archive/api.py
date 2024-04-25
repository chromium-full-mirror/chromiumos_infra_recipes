# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sysroot archive functions."""

import dataclasses
import re
from typing import Optional

from PB.chromite.api import artifacts
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.sysroot import SysrootExtractArchiveRequest
import PB.chromiumos.common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties
from recipe_engine import recipe_api

# Number of seconds to wait on gsutil ops.
GSUTIL_TIMEOUT_SECONDS = 30 * 60


@dataclasses.dataclass
class ArchivePathInfo:
  """Information parsed from a sysroot archive's GS:// path.

  Attributes:
    chromeos_version: The version of the archive, such as R99-12345.0.0-12345.
    cl_count: The number of commits from ChromeOS version to current manifest
      version.
  """
  chromeos_version: str
  cl_count: int


class SysrootArchiveApi(recipe_api.RecipeApi):
  """A module for interacting with sysroot archive."""

  def __init__(self, props: SysrootArchiveApiProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.sysroot_enabled = props.sysroot_enabled

  def extract_sysroot_build(
      self,
      chroot: common_pb2.Chroot,
      build_target: common_pb2.BuildTarget,
      sysroot_archive_gs_path: str = '',
  ) -> None:
    """Downloads the provided archive from GS and places it in the sysroot.

    Args:
      chroot: The chroot to use.
      build_target: The build target of the sysroot archive.
      sysroot_archive_gs_path: Path of archive to be unarchived.

    Raises:
      StepFailure: The archive does not exist.
    """
    with self.m.step.nest('extract sysroot archive'):
      # Raises a StepFailure if archive does not exist.
      self.m.gsutil.list(
          sysroot_archive_gs_path,
          timeout=GSUTIL_TIMEOUT_SECONDS,
          stdout=self.m.raw_io.output_text(name='ls results',
                                           add_output_log=True),
      )

      sysroot_archive_gs_short_path = (
          sysroot_archive_gs_path.removeprefix('gs://%s/' %
                                               self.sysroot_enabled.gs_bucket))
      tmp_dir = self.m.path.mkdtemp(prefix='sysroot-archive')
      download_path = tmp_dir.joinpath(
          self.m.path.basename(sysroot_archive_gs_path))
      self.m.gsutil.download(
          self.sysroot_enabled.gs_bucket,
          sysroot_archive_gs_short_path,
          download_path,
      )

      request = SysrootExtractArchiveRequest(
          build_target=build_target,
          chroot=chroot,
          sysroot_archive=common_pb2.Path(
              path=str(download_path), location=common_pb2.Path.OUTSIDE),
      )
      self.m.cros_build_api.SysrootService.ExtractArchive(request)

  def parse_archive_path(self, gs_path: str) -> Optional[ArchivePathInfo]:
    """Parses the ChromeOS version and cl count of GS archive path.

    Args:
      gs_path: Path of the sysroot archive.

    Returns:
      Parsed ChromeOS version and cl diff count.
    """
    # regex_num matches any number with no extra leading zeros.
    # Examples: 123, 1, 0, but not 0123.
    regex_num = r'(?:0|[1-9][0-9]*)'
    # example: 12345.0.0
    regex_cros_short_version = rf'{regex_num}\.{regex_num}\.{regex_num}'
    # example: R99-12345.0.0 or R99-12345.0.0-12345
    regex_cros_snapshot_version = (
        rf'R{regex_num}-{regex_cros_short_version}(?:-{regex_num})?')

    regex_bucket = r'[^/]+'
    regex_build_target = r'[^/]+'
    # example: R99-12345.0.0~16
    regex_cros_version = (
        rf'(?P<chromeos_version>{regex_cros_snapshot_version})(~(?P<cl_count>{regex_num}))?'
    )

    regex_build_suffix = r'[^/~-]+'
    regex_filename = r'[^/]+'
    # example: gs://bucket/eve/R99-12345.0.0-12345~15/archive.tar.tz
    regex_search = (
        rf'^gs://{regex_bucket}/{regex_build_target}/{regex_cros_version}-'
        rf'{regex_build_suffix}/{regex_filename}$')

    if not (m := re.match(regex_search, gs_path)):
      raise ValueError(
          f'Argument gs_path: {gs_path} is not a valid archive path.')

    return ArchivePathInfo(
        chromeos_version=m.group('chromeos_version'),
        cl_count=int(m.group('cl_count') or '0'),
    )

  def find_best_archive(self,
                        build_target: common_pb2.BuildTarget) -> Optional[str]:
    """Returns the sysroot archive path closest to the given version.

    The function calculates the cl diff count between given CrOS version and
    sysroot archives. And returns an arbitrary sysroot archive with smallest
    cl diff count.

    Args:
      build_target: The build target of the sysroot archive.

    Returns:
      A string indicates the best gs archive path or None if not found.
    """
    if not self.sysroot_enabled.use_sysroot_archive:
      return None

    path = 'gs://%s/%s/%s*/*' % (
        self.sysroot_enabled.gs_bucket,
        build_target.name,
        self.sysroot_enabled.chromeos_start_version,
    )

    with self.m.step.nest('find best sysroot archive'):
      try:
        files = self.m.gsutil.list(
            path,
            timeout=GSUTIL_TIMEOUT_SECONDS,
            stdout=self.m.raw_io.output_text(name='ls results',
                                             add_output_log=True),
        ).stdout.split()
      except self.m.step.StepFailure:
        files = []

      best_uri: Optional[str] = None
      best_cl_count = 0
      for uri in files:
        try:
          info = self.parse_archive_path(uri)
        except ValueError:
          continue
        if info.chromeos_version != self.sysroot_enabled.chromeos_start_version:
          continue
        if best_uri is None or abs(
            self.sysroot_enabled.chromeos_cl_diff_counts -
            info.cl_count) < abs(self.sysroot_enabled.chromeos_cl_diff_counts -
                                 best_cl_count):
          best_uri = uri
          best_cl_count = info.cl_count
    return best_uri

  def extract_best_archive(self, chroot: common_pb2.Chroot,
                           build_target: common_pb2.BuildTarget) -> None:
    """Finds and extracts the sysroot archive closest to the given version.

    Args:
      chroot: The chroot to use.
      build_target: build target.
    """
    if best_uri := self.find_best_archive(build_target):
      self.extract_sysroot_build(chroot, build_target, best_uri)

  def archive_sysroot_build(self, chroot: common_pb2.Chroot, sysroot: Sysroot,
                            build_target: common_pb2.BuildTarget) -> None:
    """Archives sysroot into gs bucket.

    The gs path format of the archive should be:
      gs://bucket/board/chromeos_version~cl_diff_count-build_id/archive_name.

    Args:
      chroot: The chroot to use.
      sysroot: The sysroot to use.
      build_target: The build target of the sysroot archive.
    """
    if not self.sysroot_enabled.save_sysroot_archive:
      return

    with self.m.step.nest('archive sysroot'):
      tempdir = self.m.path.mkdtemp()
      artifact_info = common_pb2.ArtifactsByService(
          sysroot=common_pb2.ArtifactsByService.Sysroot(
              output_artifacts=[
                  common_pb2.ArtifactsByService.Sysroot.ArtifactInfo(
                      artifact_types=[
                          common_pb2.ArtifactsByService.Sysroot.ArtifactType
                          .SYSROOT_ARCHIVE
                      ])
              ],
          ))
      request = artifacts.GetRequest(
          chroot=chroot, sysroot=sysroot, artifact_info=artifact_info,
          result_path=common_pb2.ResultPath(
              path=common_pb2.Path(
                  path=str(tempdir), location=common_pb2.Path.OUTSIDE)))
      response = self.m.cros_build_api.ArtifactsService.Get(
          request, infra_step=True)

      build_id = str(
          self.m.buildbucket.build.id or self.m.led.run_id.replace('/', '_'))
      gs_archive_folder = '%s/%s' % (
          build_target.name, self.sysroot_enabled.chromeos_start_version)
      if self.sysroot_enabled.chromeos_cl_diff_counts:
        gs_archive_folder += '~%d' % self.sysroot_enabled.chromeos_cl_diff_counts
      gs_archive_folder += '-%s' % build_id

      for artifact in response.artifacts.sysroot.artifacts:
        if not artifact.failed and artifact.artifact_type == common_pb2.ArtifactsByService.Sysroot.ArtifactType.SYSROOT_ARCHIVE:
          for archive in artifact.paths:
            gs_path = self.m.path.join(gs_archive_folder,
                                       self.m.path.basename(archive.path))
            self.m.gsutil.upload(archive.path, self.sysroot_enabled.gs_bucket,
                                 gs_path)
