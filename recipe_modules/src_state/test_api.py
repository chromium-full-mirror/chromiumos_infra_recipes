# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
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

from . import common


class SrcStateApi(recipe_test_api.RecipeTestApi):
  """Source State related attributes for Chrome OS recipes."""

  # This is here only for test coverage.
  _ManifestProject = common.ManifestProject

  def __init__(self, properties, *args, **kwargs):
    super(SrcStateApi, self).__init__(*args, **kwargs)
    self._workspace_path = None

  @property
  def default_ref(self):
    """The default ref for Chrome OS repos"""
    return common.default_ref

  @property
  def default_branch(self):
    """The default branch for Chrome OS repos"""
    return common.default_branch

  @property
  def workspace_path(self):
    """The "workspace" checkout path.

    The cros_source module checks out the Chrome OS source in this directory.
    It will contain the base checkout and any modifications made by the build,
    and is discarded after the build.
    """
    if not self._workspace_path:
      self._workspace_path = self.m.path['start_dir'].join(common.WORKSPACE)
    return self._workspace_path

  @workspace_path.setter
  def workspace_path(self, value):
    """Set the workspace_path for testing."""
    self._workspace_path = value

  @property
  def internal_manifest(self):
    """Information about internal manifest.

    Provides immutable information about the Chrome OS internal manifest.

    Returns:
      (ManifestProject): information about the internal manifest.
    """
    return common.ManifestProject.by_name('internal', self.workspace_path)

  @property
  def external_manifest(self):
    """Information about external manifest.

    Provides immutable information about the Chrome OS external manifest.

    Returns:
      (ManifestProject): information about the external manifest.
    """
    return common.ManifestProject.by_name('external', self.workspace_path)
