# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing frequently needed values, that we sometimes override.

If you are using cros_source or cros_infra_config, this module is relevant to
your interests.

There are two classes of properties in this module.

1. Constant(ish) things that need a common home to avoid duplication, such as
   workspace_path, internal_manifest, and external_manifest.

   All of these exist in both api.py and test_api.py, for your testing
   convenience.

2. Information obtained from recipe_engine, which we frequently change:

   These are not in the test API.
"""

from recipe_engine import recipe_test_api

from RECIPE_MODULES.chromeos.src_state import common


class SrcStateApi(recipe_test_api.RecipeTestApi):
  """Source State related attributes for CrOS recipes."""

  # This is here only for test coverage.
  ManifestProject = common.ManifestProject

  @property
  def default_ref(self):
    """The default ref for CrOS repos"""
    return common.default_ref

  @property
  def default_branch(self):
    """The default branch for CrOS repos"""
    return common.default_branch

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    The cros_source module checks out the CrOS source in this directory.
    It will contain the base checkout and any modifications made by the build,
    and is discarded after the build.
    """
    return self.m.path.cleanup_dir.join(common.WORKSPACE)

  @property
  def internal_manifest(self):
    """Information about internal manifest.

    Provides immutable information about the CrOS internal manifest.

    Returns:
      (ManifestProject): information about the internal manifest.
    """
    return common.ManifestProject.by_name('internal', self.workspace_path)

  @property
  def external_manifest(self):
    """Information about external manifest.

    Provides immutable information about the CrOS external manifest.

    Returns:
      (ManifestProject): information about the external manifest.
    """
    return common.ManifestProject.by_name('external', self.workspace_path)
