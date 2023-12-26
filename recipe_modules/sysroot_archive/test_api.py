# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers to test sysroot archive api."""

from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties
from recipe_engine import recipe_test_api


class SysrootArchiveTestApi(recipe_test_api.RecipeTestApi):
  """Helpers to test sysroot archive api."""

  @staticmethod
  def get_gsutil_list_testdata(api):
    """Returns an non-empty sysroot archive dataset."""
    return api.step_data(
        'find best sysroot archive.gsutil list',
        stdout=api.raw_io.output_text('''
gs://foo/board1/R120-15650.0.0-abc/sysroot.tar.zst
gs://foo/board1/R120-15650.0.0~15-abc/sysroot.tar.zst
gs://foo/board1/unparsable/sysroot.tar.zst
      '''),
        retcode=0,
    )

  @staticmethod
  def get_gsutil_list_empty_testdata(api):
    """Returns an empty sysroot archive dataset."""
    return api.step_data(
        'find best sysroot archive.gsutil list',
        stdout=api.raw_io.output_text(''),
        retcode=1,
    )

  @staticmethod
  def get_sysroot_archive_properties(
      api,
      save_sysroot_archive: bool,
      use_sysroot_archive: bool,
      chromeos_start_version: str,
      chromeos_end_version: str,
      chromeos_cl_diff_counts: int,
  ):
    """Returns API properties for testing sysroot_archive.

    Args:
        api: See RunSteps documentation.
        save_sysroot_archive: True if saves the sysroot archive.
        use_sysroot_archive: To use sysroot archive during building images.
        chromeos_start_version: Chrome OS start version of the sysroot archive.
        chromeos_end_version: Chrome OS end version of the sysroot archive.
        chromeos_cl_diff_counts: Chrome OS CL diff counts from Chrome OS start
          version.

    Returns:
        API properties for testing sysroot_archive.
    """
    return api.properties(
        **{
            '$chromeos/sysroot_archive':
                SysrootArchiveApiProperties(
                    sysroot_enabled=SysrootArchiveApiProperties.SysrootEnabled(
                        save_sysroot_archive=save_sysroot_archive,
                        use_sysroot_archive=use_sysroot_archive,
                        gs_bucket='foo',
                        chromeos_start_version=chromeos_start_version,
                        chromeos_end_version=chromeos_end_version,
                        chromeos_cl_diff_counts=chromeos_cl_diff_counts,
                    ))
        })
