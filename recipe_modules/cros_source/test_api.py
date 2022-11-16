# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosSourceTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_source module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def __init__(self, *args, **kwargs):
    super(CrosSourceTestApi, self).__init__(*args, **kwargs)
    self._manifest_branch = None

  @property
  def manifest_branch(self):
    """Returns any non-default manifest branch that is checked out."""
    return self._manifest_branch

  @manifest_branch.setter
  def manifest_branch(self, val):
    self._manifest_branch = val

  def test(self, name, manifest_branch, *args, **kwargs):  # pylint: disable=arguments-differ
    """Create a test with properties.

    Args:
      cros_source_properties (dict): module properties for cros_source.
      manifest_branch: manifest branch to use in repo init.
      args (list): args for api.test()
      kwargs (dict): kwargs for api.test_util.test_build.  Defaults applied:
        - cq = True.
        - revision = arbitrary sha.
        - git_repo = internal manifest url.
        - git_ref = refs/heads/${manifest_branch} (if not cq).

    Returns:
      (TestData) the build with cros_source properties included.
    """
    kwargs = kwargs or {}
    cros_source_properties = kwargs.pop('cros_source_properties', {})
    kwargs.setdefault('revision', '2d72510e447ab60a9728aeea2362d8be2cbd7789')
    kwargs.setdefault('git_repo', self.m.src_state.internal_manifest.url)
    kwargs.setdefault('cq', True)
    kwargs.setdefault('git_ref', 'refs/heads/%s' % manifest_branch)

    data = self.m.test_util.test_build(**kwargs).build
    if cros_source_properties:
      data += self.m.properties(
          **{'$chromeos/cros_source': cros_source_properties})

    return super(CrosSourceTestApi, self).test(name, data, *args)

  @recipe_test_api.mod_test_data
  @staticmethod
  def snapshot_xml_exists(value):
    return value
